"""Where the Garmin key lives: the OS keychain, with an environment override and a file fallback.

Lookup order: GARMIN_API_KEY environment variable -> OS keychain -> owner-only fallback file
(only written when no keychain exists and the user explicitly agreed).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import keyring
import keyring.backends.fail
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

from .auth import normalize_key
from .errors import GarminError

SERVICE = "garmin-dynamic-mcp"
ACCOUNT = "api-key"
ENV_VAR = "GARMIN_API_KEY"
KeySource = Literal["env", "keychain", "file"]

_SETUP = "Run: uvx garmin-dynamic-mcp setup"


class KeychainUnavailable(Exception):
    """No OS keychain backend is available on this machine."""


def fallback_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "garmin-dynamic-mcp" / "api-key"


def keychain_available() -> bool:
    backend = keyring.get_keyring()
    if isinstance(backend, keyring.backends.fail.Keyring):
        return False
    priority = getattr(backend, "priority", 1)
    return bool(priority > 0)


def _read_keychain() -> str | None:
    try:
        return keyring.get_password(SERVICE, ACCOUNT)
    except NoKeyringError:
        return None
    except KeyringError as err:
        raise GarminError(
            "key_missing",
            f"The system keychain could not be read ({type(err).__name__}). Run: uvx garmin-dynamic-mcp doctor",
        ) from None


def load_key(env: Mapping[str, str], home: Path | None = None) -> tuple[str, KeySource]:
    if env.get(ENV_VAR, "").strip():
        return normalize_key(env[ENV_VAR]), "env"
    stored = _read_keychain()
    if stored:
        return normalize_key(stored), "keychain"
    path = fallback_path(home)
    if path.is_file():
        return normalize_key(path.read_text(encoding="utf-8")), "file"
    raise GarminError("key_missing", f"No Garmin key found. {_SETUP}")


def _write_owner_only(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    if os.name != "nt":
        os.chmod(path, 0o600)


def save_key(key: str, *, allow_file: bool = False, home: Path | None = None) -> KeySource:
    clean = normalize_key(key)
    if keychain_available():
        keyring.set_password(SERVICE, ACCOUNT, clean)
        return "keychain"
    if not allow_file:
        raise KeychainUnavailable("no OS keychain backend is available")
    _write_owner_only(fallback_path(home), clean)
    return "file"


def delete_key(home: Path | None = None) -> list[KeySource]:
    found: list[KeySource] = []
    try:
        if keyring.get_password(SERVICE, ACCOUNT) is not None:
            keyring.delete_password(SERVICE, ACCOUNT)
            found.append("keychain")
    except (NoKeyringError, PasswordDeleteError):
        pass
    path = fallback_path(home)
    if path.is_file():
        path.unlink()
        found.append("file")
    return found
