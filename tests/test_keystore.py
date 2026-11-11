import os
import stat

import keyring
import pytest
from keyring.errors import KeyringError

from garmin_dynamic_mcp.errors import GarminError
from garmin_dynamic_mcp.keystore import (
    ACCOUNT,
    SERVICE,
    KeychainUnavailable,
    delete_key,
    fallback_path,
    keychain_available,
    load_key,
    save_key,
)


def test_fallback_path_is_under_config(tmp_path):
    assert fallback_path(tmp_path) == tmp_path / ".config" / "garmin-dynamic-mcp" / "api-key"


def test_env_wins_over_keychain():
    keyring.set_password(SERVICE, ACCOUNT, "kc-key")
    assert load_key({"GARMIN_API_KEY": " env-key "}) == ("env-key", "env")


def test_keychain_used_when_no_env():
    keyring.set_password(SERVICE, ACCOUNT, "kc-key")
    assert load_key({}) == ("kc-key", "keychain")


def test_file_fallback_is_normalized(tmp_path, no_keychain):
    path = fallback_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("﻿file-key\n", encoding="utf-8")
    assert load_key({}, home=tmp_path) == ("file-key", "file")


def test_missing_everywhere_says_run_setup(tmp_path, no_keychain):
    with pytest.raises(GarminError) as exc:
        load_key({}, home=tmp_path)
    assert exc.value.kind == "key_missing"
    assert "uvx garmin-dynamic-mcp setup" in exc.value.message


def test_locked_keychain_gives_doctor_hint_without_backend_details(tmp_path, memory_keyring, monkeypatch):
    def denied(*_args):
        raise KeyringError("access denied for secret thing")

    monkeypatch.setattr(memory_keyring, "get_password", denied)
    with pytest.raises(GarminError) as exc:
        load_key({}, home=tmp_path)
    assert "doctor" in exc.value.message and "secret thing" not in exc.value.message


def test_keychain_available_true_with_memory_backend():
    assert keychain_available() is True


def test_keychain_available_false_without_backend(no_keychain):
    assert keychain_available() is False


def test_save_to_keychain_normalizes():
    assert save_key(' "kc-key"\n') == "keychain"
    assert keyring.get_password(SERVICE, ACCOUNT) == "kc-key"


def test_save_without_keychain_requires_allow_file(tmp_path, no_keychain):
    with pytest.raises(KeychainUnavailable):
        save_key("file-key", home=tmp_path)
    assert not fallback_path(tmp_path).exists()
    assert save_key("file-key", allow_file=True, home=tmp_path) == "file"
    assert fallback_path(tmp_path).read_text(encoding="utf-8").strip() == "file-key"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_fallback_file_is_owner_only(tmp_path, no_keychain):
    save_key("file-key", allow_file=True, home=tmp_path)
    assert stat.S_IMODE(fallback_path(tmp_path).stat().st_mode) == 0o600


def test_delete_reports_where_the_key_was(tmp_path):
    keyring.set_password(SERVICE, ACCOUNT, "kc-key")
    path = fallback_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("file-key", encoding="utf-8")
    assert delete_key(home=tmp_path) == ["keychain", "file"]
    assert keyring.get_password(SERVICE, ACCOUNT) is None and not path.exists()
    assert delete_key(home=tmp_path) == []
