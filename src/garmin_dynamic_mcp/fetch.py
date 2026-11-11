"""Activity pagination and splitting of long date ranges."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .catalog import Catalog, Endpoint
from .client import GarminClient
from .compact import ACTIVITY_SEARCH_PATH
from .errors import GarminError

MAX_REQUESTS = 20
MAX_ACTIVITIES = 1000
DEFAULT_PAGE_SIZE = 100
_NON_NEGATIVE_INT = re.compile(r"\d+", re.ASCII)


@dataclass(frozen=True)
class FetchResult:
    data: Any
    notes: tuple[str, ...]
    partial: bool


class Fetcher:
    def __init__(self, client: GarminClient, catalog: Catalog) -> None:
        self.client = client
        self.catalog = catalog

    async def fetch(self, path: str, params: Mapping[str, str]) -> FetchResult:
        endpoint = self.catalog.validate(path, params)
        window = self._window(endpoint, params)
        if path == ACTIVITY_SEARCH_PATH:
            return await self._activities(endpoint, params)
        if window and endpoint.max_range_days and (window[1] - window[0]).days + 1 > endpoint.max_range_days:
            return await self._chunked(endpoint, params, window)
        return FetchResult(await self._call(endpoint, params), (), False)

    async def _call(self, endpoint: Endpoint, params: Mapping[str, str]) -> Any:
        url_path, query = self.catalog.expand(endpoint, params)
        return await self.client.get_json(url_path, query)

    @staticmethod
    def _window(endpoint: Endpoint, params: Mapping[str, str]) -> tuple[date, date] | None:
        """The requested date range (format already validated), checking its order."""
        if not endpoint.range_params:
            return None
        first, second = endpoint.range_params
        if first not in params or second not in params:
            return None
        start, end = date.fromisoformat(params[first]), date.fromisoformat(params[second])
        if end < start:
            raise GarminError(
                "invalid_request",
                f"Date range is reversed: {first}={params[first]} is after {second}={params[second]}.",
            )
        return start, end

    async def _activities(self, endpoint: Endpoint, params: Mapping[str, str]) -> FetchResult:
        for name in ("start", "limit"):
            if name in params and not _NON_NEGATIVE_INT.fullmatch(params[name]):
                raise GarminError(
                    "invalid_request", f"Parameter {name} must be a non-negative integer (got: {params[name]!r})."
                )
        start = int(params.get("start", 0))
        user_limit = int(params["limit"]) if "limit" in params else None
        cap = min(user_limit, MAX_ACTIVITIES) if user_limit is not None else MAX_ACTIVITIES
        page = endpoint.max_page_size or DEFAULT_PAGE_SIZE
        base = {k: v for k, v in params.items() if k not in ("start", "limit")}
        items: list[Any] = []
        requests = 0
        while len(items) < cap:
            if requests >= MAX_REQUESTS:
                note = (
                    f"Partial result: reached the cap of {MAX_REQUESTS} requests "
                    f"({len(items)} activities received). Narrow the request with startDate/endDate."
                )
                return FetchResult(items, (note,), True)
            want = min(page, cap - len(items))
            batch = await self._call(endpoint, {**base, "start": str(start), "limit": str(want)}) or []
            requests += 1
            if not isinstance(batch, list):
                raise GarminError("upstream", "Garmin answered the activity search with an unexpected format.")
            items.extend(batch)
            start += len(batch)
            if len(batch) < want:
                return FetchResult(items, (), False)
        if cap == MAX_ACTIVITIES and len(items) >= MAX_ACTIVITIES:
            note = (
                f"Partial result: reached the cap of {MAX_ACTIVITIES} activities; there may be more. "
                "Narrow the request with startDate/endDate."
            )
            return FetchResult(items, (note,), True)
        return FetchResult(items, (), False)

    async def _chunked(self, endpoint: Endpoint, params: Mapping[str, str], window: tuple[date, date]) -> FetchResult:
        first, second = endpoint.range_params  # type: ignore[misc]
        size = timedelta(days=endpoint.max_range_days - 1)  # type: ignore[operator]
        start, end = window
        results: list[Any] = []
        cursor = start
        while cursor <= end:
            if len(results) >= MAX_REQUESTS:
                note = (
                    f"Partial result: reached the cap of {MAX_REQUESTS} requests. "
                    f"Covered {start} – {cursor - timedelta(days=1)}; "
                    f"missing {cursor} to {end}. Ask for the rest in a second call."
                )
                return FetchResult(self._merge(results), (note,), True)
            chunk_end = min(cursor + size, end)
            chunk = {**params, first: cursor.isoformat(), second: chunk_end.isoformat()}
            try:
                results.append(await self._call(endpoint, chunk))
            except GarminError as err:
                if not results:
                    raise
                note = (
                    f"Partial result: covered {start} – {cursor - timedelta(days=1)}; "
                    f"the part from {cursor} to {end} failed: {err.message}"
                )
                return FetchResult(self._merge(results), (note,), True)
            cursor = chunk_end + timedelta(days=1)
        return FetchResult(self._merge(results), (), False)

    @staticmethod
    def _merge(results: list[Any]) -> Any:
        """Merge chunk results: lists concatenated, {"data": [...]} joined."""
        if all(r is None or isinstance(r, list) for r in results):
            return [item for r in results if r for item in r]
        if all(isinstance(r, dict) and isinstance(r.get("data"), list) for r in results if r is not None):
            return {"data": [item for r in results if r for item in r["data"]]}
        return results
