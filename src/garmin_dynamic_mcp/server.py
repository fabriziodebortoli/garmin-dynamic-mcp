"""MCP server (stdio) with two generic tools: list_endpoints and get."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .auth import TokenManager
from .catalog import Catalog, load_catalog
from .client import GarminClient
from .compact import compact, truncate
from .errors import GarminError
from .fetch import Fetcher
from .keystore import KeySource, load_key
from .updates import UpdateChecker
from .version import __version__

KeyLoader = Callable[[Mapping[str, str]], tuple[str, KeySource]]

log = logging.getLogger("garmin_dynamic_mcp")

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

INSTRUCTIONS = (
    "Read-only access to the user's own Garmin Connect data (Personal API). "
    "Call list_endpoints first to see which endpoints exist and which parameters they take, "
    "then call get(path, params, fields). Use `fields` (dotted paths such as 'activityType.typeKey') "
    "to receive only the fields you need. Distances are in meters, durations in seconds, "
    "speeds in m/s. Do the aggregation (sums, averages, grouping by day) yourself on the returned rows."
)


class _Runtime:
    """Components created on the first call, so the server starts even without a key."""

    def __init__(self, env: Mapping[str, str], http: httpx.AsyncClient | None, key_loader: KeyLoader) -> None:
        self.env = env
        self.http = http
        self.key_loader = key_loader
        self.fetcher: Fetcher | None = None
        self.tokens: TokenManager | None = None
        self.checker: UpdateChecker | None = None
        self.catalog: Catalog = load_catalog(allow_sensitive=env.get("GARMIN_MCP_ENABLE_SENSITIVE") == "1")

    def client(self) -> httpx.AsyncClient:
        if self.http is None:
            self.http = httpx.AsyncClient(timeout=60)
        return self.http

    def update_notice(self) -> dict[str, str] | None:
        """Start the (background, once per process) update check and return its notice so far."""
        if self.checker is None:
            self.checker = UpdateChecker(__version__, self.client(), self.env)
        self.checker.start()
        return self.checker.notice

    def ensure(self) -> tuple[Fetcher, TokenManager]:
        if self.fetcher is None or self.tokens is None:
            key, _source = self.key_loader(self.env)
            self.tokens = TokenManager(key, self.client())
            self.fetcher = Fetcher(GarminClient(self.tokens, self.client()), self.catalog)
        return self.fetcher, self.tokens


def _param_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_server(
    env: Mapping[str, str],
    http: httpx.AsyncClient | None = None,
    key_loader: KeyLoader = load_key,
) -> MCPServer:
    server = MCPServer(
        "garmin",
        title="Garmin Dynamic MCP",
        version=__version__,
        website_url="https://github.com/fabriziodebortoli/garmin-dynamic-mcp",
        instructions=INSTRUCTIONS,
    )
    runtime = _Runtime(env, http, key_loader)

    @server.tool(title="List Garmin endpoints", annotations=READ_ONLY)
    async def list_endpoints(query: str | None = None) -> str:
        """List the Garmin Personal API endpoints this server can call, with their parameters.

        query: optional case-insensitive text matched against path and summary (e.g. "sleep").

        Each entry has: path, summary, params (name, location 'path' or 'query', required, type),
        verified (whether the endpoint was tested against a real account), disabled (sensitive
        endpoints are off unless GARMIN_MCP_ENABLE_SENSITIVE=1) and, when known,
        max_range_days (longer date ranges are split automatically). Date parameters use YYYY-MM-DD.
        If the answer contains update_available, tell the user once (version and how to update).
        """
        notice = runtime.update_notice()
        entries = []
        needle = (query or "").strip().lower()
        for path, endpoint in sorted(runtime.catalog.endpoints.items()):
            if needle and needle not in (path + " " + endpoint.summary).lower():
                continue
            disabled = endpoint.sensitive and not runtime.catalog.allow_sensitive
            entry: dict[str, Any] = {
                "path": path,
                "summary": endpoint.summary,
                "verified": endpoint.verified,
                "disabled": disabled,
            }
            if not disabled:
                entry["params"] = [
                    {
                        "name": p.name,
                        "location": p.location,
                        "required": p.required,
                        "type": p.type,
                        "description": p.description,
                    }
                    for p in endpoint.params
                ]
                if endpoint.max_range_days:
                    entry["max_range_days"] = endpoint.max_range_days
                if endpoint.max_page_size:
                    entry["max_page_size"] = endpoint.max_page_size
            entries.append(entry)
        payload: dict[str, Any] = {"endpoints": entries}
        if needle and not entries:
            payload["note"] = f"No endpoint matches '{query}'. Call list_endpoints without query to see all."
        if notice:
            payload["update_available"] = notice
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @server.tool(title="Read Garmin data", annotations=READ_ONLY)
    async def get(
        path: str,
        params: dict[str, str | int | float | bool] | None = None,
        fields: list[str] | None = None,
    ) -> str:
        """Call one Garmin Personal API endpoint (GET only) and return compact JSON.

        path: an endpoint path exactly as listed by list_endpoints (with the {placeholders}).
        params: values for that endpoint's path and query parameters, e.g.
          {"startDate": "2026-11-01", "endDate": "2026-11-09"}. For the activity search endpoint,
          `limit` is the total number of activities wanted (pages are fetched automatically, up to
          1000) and startDate/endDate filter by date.
        fields: optional dotted paths to keep, e.g. ["startTimeLocal", "distance",
          "averageRunningCadenceInStepsPerMinute"]. Activities come with a useful default set
          when fields is omitted.
        Returns {"data": ..., "partial": bool, "notes": [...], "key_warning": str|null}.
        If partial is true, read notes: the result was cut and says how to narrow the request.
        Responses are capped at about 40,000 characters (roughly 150 activities in the default view):
        for long periods pass a short `fields` list. If key_warning is not null, tell the user.
        If update_available is present, tell the user once (version and how to update).
        """
        try:
            notice = runtime.update_notice()
            fetcher, tokens = runtime.ensure()
            result = await fetcher.fetch(path, {k: _param_text(v) for k, v in (params or {}).items()})
            reduced, compact_notes = compact(path, result.data, fields)
            data, cut_note = truncate(reduced)
            notes = list(result.notes) + compact_notes + ([cut_note] if cut_note else [])
            payload: dict[str, Any] = {
                "data": data,
                "partial": result.partial or cut_note is not None,
                "notes": notes,
                "key_warning": tokens.key_expiry_warning,
            }
            if notice:
                payload["update_available"] = notice
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except GarminError as err:
            raise ToolError(err.message) from None
        except ToolError:
            raise
        except Exception as err:  # must never reveal details or the key
            log.error("unexpected error in get: %s", type(err).__name__)
            raise ToolError(f"Unexpected error in garmin-dynamic-mcp ({type(err).__name__}).") from None

    return server


def serve() -> None:
    """Run the MCP server over stdio (what MCP clients launch)."""
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    build_server(os.environ).run()
