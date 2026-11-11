import base64
import json
import sys
from pathlib import Path

import keyring
import keyring.backends.fail
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def make_jwt(iat: int, exp: int) -> str:
    """Unsigned JWT in the right format, for tests."""

    def part(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'iat': iat, 'exp': exp})}.sig"


class MemoryKeyring(KeyringBackend):
    """In-memory keychain so that no test ever touches the real OS keychain."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch, tmp_path):
    """Isolate every test: in-memory keychain and a temporary home directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    ring = MemoryKeyring()
    keyring.set_keyring(ring)
    yield ring


@pytest.fixture
def no_keychain():
    keyring.set_keyring(keyring.backends.fail.Keyring())
