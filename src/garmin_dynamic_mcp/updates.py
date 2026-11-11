"""Tell the user when a newer release exists. Never updates anything by itself.

One background request to PyPI per server process (3-second timeout). Any failure is silent.
Opt out with GARMIN_MCP_NO_UPDATE_CHECK=1.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping

import httpx

PYPI_URL = "https://pypi.org/pypi/garmin-dynamic-mcp/json"
RELEASES_URL = "https://github.com/fabriziodebortoli/garmin-dynamic-mcp/releases/tag/v{version}"
OPT_OUT_VAR = "GARMIN_MCP_NO_UPDATE_CHECK"
HOW_TO_UPDATE = "Run: uvx garmin-dynamic-mcp@latest update — then restart your MCP client."
_TIMEOUT_S = 3.0
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)", re.ASCII)


def parse_version(text: str) -> tuple[int, ...] | None:
    """Parse a final release version 'X.Y.Z'; pre-releases and anything else give None."""
    match = _VERSION_RE.fullmatch(text.strip())
    return tuple(int(part) for part in match.groups()) if match else None


class UpdateChecker:
    def __init__(self, current: str, http: httpx.AsyncClient, env: Mapping[str, str]) -> None:
        self.current = current
        self._http = http
        self._disabled = env.get(OPT_OUT_VAR, "").strip() not in ("", "0")
        self._task: asyncio.Task[None] | None = None
        self._latest: str | None = None

    def start(self) -> None:
        """Start the check once, in the background; never waits for it."""
        if self._disabled or self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._check())

    async def _check(self) -> None:
        try:
            response = await self._http.get(PYPI_URL, timeout=_TIMEOUT_S)
            if response.status_code != 200:
                return
            latest = str(response.json()["info"]["version"])
        except Exception:  # a failed check must never affect the tools
            return
        latest_v, current_v = parse_version(latest), parse_version(self.current)
        if latest_v and current_v and latest_v > current_v:
            self._latest = latest

    @property
    def notice(self) -> dict[str, str] | None:
        if self._latest is None:
            return None
        return {
            "current": self.current,
            "latest": self._latest,
            "how_to_update": HOW_TO_UPDATE,
            "release_notes": RELEASES_URL.format(version=self._latest),
        }
