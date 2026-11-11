"""Garmin personal API key -> access token (24 hours, no refresh token)."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable

import httpx

from .errors import GarminError

TOKEN_URL = "https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token"  # noqa: S105 (a URL, not a secret)
KEY_PAGE = "https://connect.garmin.com/app/settings/personalApiToken"
SETUP_HINT = "run: uvx garmin-dynamic-mcp setup"
_REFRESH_MARGIN_S = 60
_FULL_LIFETIME_S = 24 * 3600


def normalize_key(raw: str | None) -> str:
    """Strip spaces, line breaks and quotes pasted by mistake."""
    # drop the BOM and control characters a paste can leave behind (for example the \x16 of Ctrl+V)
    cleaned = "".join(ch for ch in (raw or "") if ch == "\n" or ch == "\t" or (ch.isprintable() or ch.isspace()))
    key = cleaned.replace("﻿", "").strip().strip("\"'").strip()
    if not key:
        raise GarminError(
            "key_missing",
            f"No Garmin key found. Create one at {KEY_PAGE} and {SETUP_HINT}",
        )
    if not key.isascii() or any(ch.isspace() for ch in key):
        raise GarminError(
            "key_missing",
            f"The Garmin key contains spaces or unexpected characters: copy it again from {KEY_PAGE} and {SETUP_HINT}",
        )
    return key


def _jwt_times(token: str) -> tuple[float, float]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return float(claims["iat"]), float(claims["exp"])
    except (IndexError, KeyError, ValueError, TypeError) as err:
        raise GarminError("upstream", "Garmin returned an invalid token. Try again later.") from err


def token_lifetime(token: str) -> float:
    """Seconds between the token's issue and expiry (24 h, or less when the key expires sooner)."""
    iat, exp = _jwt_times(token)
    return exp - iat


class TokenManager:
    def __init__(
        self,
        api_key: str,
        http: httpx.AsyncClient,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._clock = clock
        self._token: str | None = None
        self._exp = 0.0
        self.key_expiry_warning: str | None = None

    def invalidate(self) -> None:
        self._token = None

    async def token(self) -> str:
        if self._token is not None and self._clock() < self._exp - _REFRESH_MARGIN_S:
            return self._token
        token = await self._exchange()
        iat, exp = _jwt_times(token)
        lifetime = exp - iat
        # Expiry measured on the local clock from the token's own lifetime, so a skewed clock
        # neither re-exchanges on every call nor keeps an expired token.
        self._token, self._exp = token, self._clock() + lifetime
        if lifetime < _FULL_LIFETIME_S:
            hours = max(0, int(lifetime // 3600))
            self.key_expiry_warning = (
                f"Your Garmin key expires in about {hours} hours: create a new one at {KEY_PAGE} and {SETUP_HINT}"
            )
        else:
            self.key_expiry_warning = None
        return token

    async def _exchange(self) -> str:
        try:
            response = await self._http.post(TOKEN_URL, headers={"Authorization": f"ApiKey {self._api_key}"})
        except httpx.TransportError as err:
            raise GarminError("network", "Cannot reach Garmin: check your connection and try again.") from err
        status = response.status_code
        if status == 404:
            # Garmin answers 404 "Personal API Key with ID ... does not exist" for a deleted or replaced key.
            raise GarminError(
                "key_rejected",
                "Your Garmin key has expired or was revoked: Garmin says it does not exist (it may have been "
                f"deleted or replaced by a newer key). Create a new key at {KEY_PAGE} and {SETUP_HINT}",
            )
        if status in (400, 401, 403):
            raise GarminError(
                "key_rejected",
                f"Your Garmin key has expired or was revoked (or is not valid). Create a new key at {KEY_PAGE} "
                f"and {SETUP_HINT}",
            )
        if status == 429:
            raise GarminError("rate_limited", "Garmin is rate-limiting requests: try again in a few minutes.")
        if status >= 400:
            raise GarminError("upstream", f"Garmin answered with an error (HTTP {status}). Try again later.")
        token = response.text.strip()
        if not token:
            raise GarminError("upstream", "Garmin answered without a token. Try again later.")
        return token
