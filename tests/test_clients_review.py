"""Regression tests for the findings of the whole-branch review (config writers)."""

import json
import os
import stat

import pytest
from test_clients import CLAUDE, ENTRY, NOW, UVX, FakeRun

from garmin_dynamic_mcp.clients import (
    cli_entry,
    configure_cli,
    read_json_entry,
    remove_json_entry,
    server_entry,
    write_json_entry,
)


def _write(path, root="mcpServers", entry=ENTRY, confirm=lambda _e: False):
    return write_json_entry("Test", path, root, entry, confirm_replace=confirm, now=NOW)


def test_replacing_our_own_entry_keeps_env_and_user_flags(tmp_path):
    path = tmp_path / "cfg.json"
    mine = {
        "command": "/old/uvx",
        "args": ["garmin-dynamic-mcp==0.1.0"],
        "env": {"GARMIN_API_KEY": "from-env", "GARMIN_MCP_NO_UPDATE_CHECK": "1"},
        "disabled": False,
        "autoApprove": ["list_endpoints"],
    }
    path.write_text(json.dumps({"mcpServers": {"garmin": mine}}), encoding="utf-8")
    assert _write(path, entry=server_entry(UVX, "0.3.0")).status == "written"
    merged = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["garmin"]
    assert merged["env"] == mine["env"] and merged["autoApprove"] == ["list_endpoints"]
    assert merged["disabled"] is False
    assert merged["command"] == UVX and merged["args"] == ["garmin-dynamic-mcp==0.3.0"]


def test_only_the_pinned_arg_is_replaced_when_the_user_added_others(tmp_path):
    path = tmp_path / "cfg.json"
    mine = {"command": "uvx", "args": ["--python", "3.12", "garmin-dynamic-mcp==0.1.0"]}
    path.write_text(json.dumps({"mcpServers": {"garmin": mine}}), encoding="utf-8")
    _write(path, entry=server_entry("uvx", "0.3.0"))
    merged = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["garmin"]
    assert merged["args"] == ["--python", "3.12", "garmin-dynamic-mcp==0.3.0"]


@pytest.mark.parametrize("encoding", ["utf-16", "cp1252"])
def test_non_utf8_files_become_snippets_and_are_untouched(tmp_path, encoding):
    path = tmp_path / "cfg.json"
    raw = '{"mcpServers": {"x": {"command": "café"}}}'.encode(encoding)
    path.write_bytes(raw)
    assert _write(path).status == "snippet"
    assert path.read_bytes() == raw
    assert read_json_entry(path, "mcpServers") is None


def test_utf8_bom_file_is_read_normally(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"mcpServers": {"a": {"command": "x"}}}).encode())
    assert _write(path).status == "written"
    assert set(json.loads(path.read_text(encoding="utf-8"))["mcpServers"]) == {"a", "garmin"}


def test_remove_reports_write_errors_instead_of_raising(tmp_path, monkeypatch):
    from garmin_dynamic_mcp import clients

    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": {"garmin": ENTRY}}), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(clients, "_atomic_write", boom)
    assert remove_json_entry("Test", path, "mcpServers").status == "error"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_rewrite_keeps_the_file_mode_and_backup_is_private(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"env": {"TOKEN": "x"}}}}), encoding="utf-8")
    path.chmod(0o600)
    _write(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    backup = next(tmp_path.glob("cfg.json.bak-garmin-*"))
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_rewrite_follows_a_symlinked_config(tmp_path):
    real = tmp_path / "dotfiles" / "mcp.json"
    real.parent.mkdir()
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "mcp.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges here")
    assert _write(link).status == "written"
    assert link.is_symlink()
    assert "garmin" in json.loads(real.read_text(encoding="utf-8"))["mcpServers"]


FOREIGN_LISTING = "Checking MCP server health...\n\ngarmin: npx other-garmin-server - ✓ Connected\n"
OURS_LISTING = "garmin: /bin/uvx garmin-dynamic-mcp==0.1.0 - ✓ Connected\n"
LOOKALIKE_LISTING = "garmin-connect: npx something - ✓ Connected\ngarminx: foo\n"


def _which(name):
    return f"/bin/{name}"


def test_cli_entry_matches_the_exact_name_only():
    assert cli_entry(CLAUDE, FakeRun(listing=LOOKALIKE_LISTING), _which) is None
    assert "other-garmin-server" in cli_entry(CLAUDE, FakeRun(listing=FOREIGN_LISTING), _which)
    assert cli_entry(CLAUDE, FakeRun(), lambda _n: None) is None


def test_cli_foreign_server_is_not_replaced_without_confirmation():
    run = FakeRun(listing=FOREIGN_LISTING)
    result = configure_cli(CLAUDE, UVX, "0.2.0", run, _which, confirm_replace=lambda _line: False)
    assert result.status == "skipped" and run.mutations() == []


def test_cli_foreign_server_is_replaced_when_confirmed():
    run = FakeRun(listing=FOREIGN_LISTING)
    result = configure_cli(CLAUDE, UVX, "0.2.0", run, _which, confirm_replace=lambda _line: True)
    assert result.status == "written" and len(run.mutations()) == 2


def test_cli_our_older_entry_is_replaced_without_asking():
    def never(_line):
        raise AssertionError("must not ask about our own entry")

    run = FakeRun(listing=OURS_LISTING)
    assert configure_cli(CLAUDE, UVX, "0.2.0", run, _which, confirm_replace=never).status == "written"


def test_cli_lookalike_name_is_not_removed_or_asked_about():
    run = FakeRun(listing=LOOKALIKE_LISTING)
    result = configure_cli(CLAUDE, UVX, "0.2.0", run, _which, confirm_replace=lambda _l: False)
    assert result.status == "written"


def test_rewrite_copies_the_original_mode_to_the_new_file_and_backup(tmp_path, monkeypatch):
    """Portable proof that the mode is carried over (the POSIX test above checks the real bits on CI)."""
    from garmin_dynamic_mcp import clients

    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": {"other": {}}}), encoding="utf-8")
    copied_modes, copied_files = [], []
    real_copymode, real_copy2 = clients.shutil.copymode, clients.shutil.copy2
    monkeypatch.setattr(
        clients.shutil, "copymode", lambda src, dst: (copied_modes.append((src, dst)), real_copymode(src, dst))
    )
    monkeypatch.setattr(
        clients.shutil, "copy2", lambda src, dst: (copied_files.append((src, dst)), real_copy2(src, dst))
    )
    _write(path)
    assert [src for src, _dst in copied_modes] == [path]
    assert [src for src, _dst in copied_files] == [path]
    assert not list(tmp_path.glob("*.tmp-garmin"))
