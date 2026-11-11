"""Live probe of the Garmin Personal API (run by a maintainer, with their own key).

Usage (PowerShell):
    $env:GARMIN_API_KEY = "<key>"; uv run python scripts/live_probe.py

Then rebuild the catalog: uv run python scripts/fetch_openapi.py build/openapi.json &&
    uv run python scripts/build_catalog.py build/openapi.json --force

What it does: calls every enabled endpoint once, measures the maximum activities per page, the
reachable history depth, the longest accepted date ranges and how Garmin answers an invalid key.
It writes build/live-probe-report.md (not committed) and updates src/garmin_dynamic_mcp/catalog_overrides.json.
Only outcomes and field *names* end up in the results: no personal values, tokens or keys.
At most 2 requests per second. Sensitive endpoints are never called.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from garmin_dynamic_mcp.auth import TOKEN_URL, TokenManager, normalize_key
from garmin_dynamic_mcp.catalog import Catalog, Endpoint, load_catalog
from garmin_dynamic_mcp.client import GarminClient
from garmin_dynamic_mcp.errors import GarminError

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES_FILE = ROOT / "src" / "garmin_dynamic_mcp" / "catalog_overrides.json"
FINDINGS_FILE = (
    ROOT / "build" / "live-probe-report.md"
)  # raw report: not committed; docs/garmin-api-findings.md is curated
PAGE_SIZES = (200, 250, 300, 400, 500, 1000)
RANGE_DAYS = (7, 14, 28, 31, 60, 90, 180, 366)
NOTE = "No personal data: only outcomes and field names."
SEARCH = "/activitylist-service/activities/search/activities"
SUMMARY_RANGE = "/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}"


def minimal_params(endpoint: Endpoint, today: date, activity_id: int | None) -> dict[str, str] | None:
    """Plausible minimal parameters for calling an endpoint, or None if they can't be made up."""
    yesterday = (today - timedelta(days=1)).isoformat()
    params: dict[str, str] = {}
    if endpoint.range_params:
        first, second = endpoint.range_params
        params[first] = (today - timedelta(days=7)).isoformat()
        params[second] = yesterday
    for p in endpoint.params:
        if p.name in params:
            continue
        is_date = "date" in p.name.lower()
        if not p.required and not is_date:
            continue
        if p.name == "activityId":
            if activity_id is None:
                return None
            params[p.name] = str(activity_id)
        elif is_date:
            params[p.name] = yesterday
        else:
            return None
    return params


def shape(data: Any) -> str:
    """Describe a response's shape: type, count and field names (never values)."""
    if data is None:
        return "empty body"
    if isinstance(data, list):
        keys = sorted(data[0]) if data and isinstance(data[0], dict) else []
        return f"list of {len(data)} items; fields of the first: {', '.join(keys[:25]) or '-'}"
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            keys = sorted(inner[0]) if inner and isinstance(inner[0], dict) else []
            return f"object with data[{len(inner)}]; fields: {', '.join(keys[:25]) or '-'}"
        return f"object; fields: {', '.join(sorted(data)[:25])}"
    return type(data).__name__


class Probe:
    def __init__(self, client: GarminClient, today: date, catalog: Catalog | None = None, delay: float = 0.5) -> None:
        self.client = client
        self.today = today
        self.delay = delay
        self.catalog = catalog or load_catalog(allow_sensitive=False)
        self.overrides: dict[str, dict[str, Any]] = {}
        self.lines: list[str] = []
        self.rate_limited = False

    def log(self, text: str) -> None:
        print(text, flush=True)
        self.lines.append(text)

    async def call(self, path: str, params: Mapping[str, str]) -> Any:
        await asyncio.sleep(self.delay)
        endpoint = self.catalog.endpoints[path]
        url_path, query = self.catalog.expand(endpoint, params)
        try:
            return await self.client.get_json(url_path, query)
        except GarminError as err:
            if err.kind == "rate_limited":
                self.rate_limited = True
            raise

    def _window(self, endpoint: Endpoint, days: int) -> dict[str, str]:
        first, second = endpoint.range_params  # type: ignore[misc]
        end = self.today - timedelta(days=1)
        return {first: (end - timedelta(days=days - 1)).isoformat(), second: end.isoformat()}

    async def first_activity_id(self) -> int | None:
        try:
            data = await self.call(SEARCH, {"start": "0", "limit": "1"})
        except GarminError:
            return None
        return data[0]["activityId"] if data else None

    async def probe_endpoints(self, activity_id: int | None) -> None:
        self.log("## Endpoints (one call each)\n")
        for path, endpoint in sorted(self.catalog.endpoints.items()):
            if endpoint.sensitive:
                self.log(f"- `{path}`: not verified (sensitive endpoint, disabled by default: not called)")
                continue
            params = minimal_params(endpoint, self.today, activity_id)
            if params is None:
                self.log(f"- `{path}`: not verified (needs parameters the probe cannot make up)")
                continue
            try:
                data = await self.call(path, params)
            except GarminError as err:
                self.log(f"- `{path}`: ERROR ({err.kind}): {err.message}")
                continue
            self.overrides.setdefault(path, {})["verified"] = True
            self.log(f"- `{path}`: ok — {shape(data)}")
            if self.rate_limited:
                self.log("\n(429 received: stopping the probe.)")
                return

    async def probe_page_size(self) -> int | None:
        self.log("\n## Maximum activities per page\n")
        best: int | None = None
        for size in PAGE_SIZES:
            try:
                await self.call(SEARCH, {"start": "0", "limit": str(size)})
            except GarminError as err:
                self.log(f"- limit={size}: error ({err.kind})")
                break
            best = size
            self.log(f"- limit={size}: ok")
        self.log(f"\nLargest usable: {best}")
        if best:
            self.overrides.setdefault(SEARCH, {})["max_page_size"] = best
        return best

    async def probe_history(self, page_size: int | None) -> None:
        self.log("\n## Activity history depth\n")
        size = page_size or 100
        oldest: str | None = None
        start = 0
        for _ in range(30):
            try:
                data = await self.call(SEARCH, {"start": str(start), "limit": str(size)})
            except GarminError as err:
                self.log(f"- error at start={start}: {err.kind}")
                break
            if not data:
                self.log(f"- pages end at start={start} (the list runs out)")
                break
            oldest = data[-1].get("startTimeLocal", "")[:10] or oldest
            start += size
        else:
            self.log("- reached the cap of 30 requests: the history may go deeper")
        if oldest:
            months = (self.today - date.fromisoformat(oldest)).days // 30
            self.log(f"- reachable history: about {months} months")

    async def probe_ranges(self) -> None:
        self.log("\n## Longest accepted date ranges\n")
        for path, endpoint in sorted(self.catalog.endpoints.items()):
            if not endpoint.range_params or endpoint.sensitive or self.rate_limited:
                continue
            best: int | None = None
            for days in RANGE_DAYS:
                try:
                    await self.call(path, self._window(endpoint, days))
                except GarminError as err:
                    self.log(f"- `{path}`: {days} days → error ({err.kind})")
                    break
                best = days
            self.log(f"- `{path}`: longest successful range = {best} days")
            if best is not None and best < RANGE_DAYS[-1]:
                self.overrides.setdefault(path, {})["max_range_days"] = best

    async def probe_summary_range(self) -> None:
        self.log("\n## `activity/summary/range`\n")
        endpoint = self.catalog.endpoints[SUMMARY_RANGE]
        for days in (7, 31, 90):
            try:
                data = await self.call(SUMMARY_RANGE, self._window(endpoint, days))
                self.log(f"- {days} days: {shape(data)}")
            except GarminError as err:
                self.log(f"- {days} days: error ({err.kind})")

    async def probe_invalid_key(self, http: httpx.AsyncClient) -> None:
        self.log("\n## Invalid key\n")
        response = await http.post(TOKEN_URL, headers={"Authorization": "ApiKey GCDC_invalid-key"})
        self.log(f"- exchange with an invalid key → HTTP {response.status_code}")

    def write_outputs(self) -> None:
        existing = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8")) if OVERRIDES_FILE.exists() else {}
        for path, values in self.overrides.items():
            existing.setdefault(path, {}).update(values)
        OVERRIDES_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        header = f"# Live probe results\n\nRun on {self.today.isoformat()}. {NOTE}\n\n"
        FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        FINDINGS_FILE.write_text(header + "\n".join(self.lines) + "\n", encoding="utf-8")


async def _run(key: str) -> int:
    async with httpx.AsyncClient(timeout=60) as http:
        client = GarminClient(TokenManager(key, http), http)
        probe = Probe(client, date.today())
        try:
            activity_id = await probe.first_activity_id()
            await probe.probe_endpoints(activity_id)
            page_size = await probe.probe_page_size()
            await probe.probe_history(page_size)
            await probe.probe_ranges()
            await probe.probe_summary_range()
            await probe.probe_invalid_key(http)
        except GarminError as err:
            print(err.message)
            return 1
        finally:
            probe.write_outputs()
    print(f"\nDone. Wrote {FINDINGS_FILE.name} and {OVERRIDES_FILE.name}.")
    return 0


def main(env: Mapping[str, str]) -> int:
    try:
        key = normalize_key(env.get("GARMIN_API_KEY"))
    except GarminError as err:
        print(err.message)
        return 2
    return asyncio.run(_run(key))


if __name__ == "__main__":
    raise SystemExit(main(os.environ))
