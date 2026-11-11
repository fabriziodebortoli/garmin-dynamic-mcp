"""Read-only HTTP client for the Garmin Personal API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .auth import KEY_PAGE, TokenManager
from .errors import GarminError

BASE_URL = "https://personal.connectapi.garmin.com"


class GarminClient:
    def __init__(self, tokens: TokenManager, http: httpx.AsyncClient) -> None:
        self._tokens = tokens
        self._http = http

    async def get_json(self, url_path: str, params: Mapping[str, str] | None = None) -> Any | None:
        if not url_path.startswith("/") or url_path.startswith("//"):
            raise GarminError("invalid_request", f"Invalid path: {url_path}")
        response = await self._request(url_path, params)
        if response.status_code == 401:
            self._tokens.invalidate()
            response = await self._request(url_path, params)
            if response.status_code == 401:
                raise GarminError(
                    "key_rejected",
                    f"Your Garmin key has expired or was revoked. Create a new key at {KEY_PAGE} "
                    "and run: uvx garmin-dynamic-mcp setup",
                )
        return self._parse(response)

    async def _request(self, url_path: str, params: Mapping[str, str] | None) -> httpx.Response:
        token = await self._tokens.token()
        try:
            return await self._http.get(
                BASE_URL + url_path,
                params=dict(params or {}),
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=False,
            )
        except httpx.TransportError as err:
            raise GarminError("network", "Cannot reach Garmin: check your connection and try again.") from err

    @staticmethod
    def _parse(response: httpx.Response) -> Any | None:
        status = response.status_code
        if status == 429:
            retry = response.headers.get("Retry-After")
            wait = f" Try again in {retry} seconds." if retry else " Try again in a few minutes."
            raise GarminError("rate_limited", "Garmin is rate-limiting requests." + wait)
        if 300 <= status < 400:
            raise GarminError("upstream", f"Garmin answered with an unexpected redirect (HTTP {status}).")
        if status >= 400:
            raise GarminError("upstream", f"Garmin answered with an error (HTTP {status}).")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as err:
            raise GarminError(
                "upstream", "Garmin answered in an unexpected format (not JSON). Try again later."
            ) from err
