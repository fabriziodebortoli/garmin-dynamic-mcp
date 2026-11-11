"""Regression tests for the findings of the whole-branch review (CLI behavior)."""

import respx
from keyring.errors import KeyringLocked, PasswordSetError
from test_cli import KEY, UVX, cursor_config, make_deps, output, token_ok
from test_clients import FakeRun
from test_clients_review import FOREIGN_LISTING, LOOKALIKE_LISTING

from garmin_dynamic_mcp import cli
from garmin_dynamic_mcp.cli import main
from garmin_dynamic_mcp.keystore import ACCOUNT, SERVICE

CLAUDE_WHICH = {"uvx": UVX, "claude": "/u/bin/claude"}.get


def _eof(_prompt):
    raise EOFError


@respx.mock
def test_setup_with_stdin_key_and_no_yes_does_not_crash_on_questions(tmp_path):
    token_ok()
    deps, _ = make_deps(tmp_path, stdin=f"{KEY}\n", ask=_eof)
    cursor_config(deps).parent.mkdir(parents=True)
    assert main(["setup", "--key-stdin"], deps) == 0
    assert KEY not in output(deps)
    assert "--clients" in output(deps)  # tells the user how to configure clients non-interactively
    assert not cursor_config(deps).exists()


@respx.mock
def test_setup_reports_a_locked_keychain_in_one_line(tmp_path, memory_keyring, monkeypatch):
    token_ok()

    def denied(*_args):
        raise PasswordSetError("denied: secret detail")

    monkeypatch.setattr(memory_keyring, "set_password", denied)
    deps, _ = make_deps(tmp_path)
    assert main(["setup", "--clients", "none"], deps) == 1
    text = output(deps)
    assert "keychain" in text.lower() and "Traceback" not in text and KEY not in text
    assert "secret detail" not in text


def test_forget_reports_a_locked_keychain_in_one_line(tmp_path, memory_keyring, monkeypatch):
    memory_keyring.set_password(SERVICE, ACCOUNT, KEY)

    def locked(*_args):
        raise KeyringLocked("locked: secret detail")

    monkeypatch.setattr(memory_keyring, "get_password", locked)
    deps, _ = make_deps(tmp_path)
    assert main(["forget"], deps) == 1
    assert "keychain" in output(deps).lower() and "secret detail" not in output(deps)


def test_unexpected_os_errors_are_one_line_not_a_traceback(tmp_path, monkeypatch):
    async def broken(_deps, _args):
        raise OSError("disk exploded")

    monkeypatch.setitem(cli._COMMANDS, "doctor", broken)
    deps, _ = make_deps(tmp_path)
    assert main(["doctor"], deps) == 1
    assert "OSError" in deps.err.getvalue() and "Traceback" not in deps.err.getvalue()


@respx.mock
def test_setup_survives_a_utf16_client_config(tmp_path):
    token_ok()
    deps, _ = make_deps(tmp_path)
    cursor_config(deps).parent.mkdir(parents=True)
    raw = '{"mcpServers": {}}'.encode("utf-16")
    cursor_config(deps).write_bytes(raw)
    assert main(["setup", "--clients", "cursor", "--yes"], deps) == 0
    assert cursor_config(deps).read_bytes() == raw and '"garmin"' in output(deps)


@respx.mock
def test_setup_asks_before_replacing_a_foreign_garmin_server_in_claude_code(tmp_path):
    token_ok()
    run = FakeRun(listing=FOREIGN_LISTING)
    deps, _ = make_deps(tmp_path, which=CLAUDE_WHICH, answers=["n"], run=run)
    assert main(["setup", "--clients", "claude-code"], deps) == 0
    assert run.mutations() == [] and "skipped" in output(deps)


@respx.mock
def test_setup_yes_replaces_a_foreign_garmin_server_in_claude_code(tmp_path):
    token_ok()
    run = FakeRun(listing=FOREIGN_LISTING)
    deps, _ = make_deps(tmp_path, which=CLAUDE_WHICH, run=run)
    assert main(["setup", "--clients", "claude-code", "--yes"], deps) == 0
    assert len(run.mutations()) == 2


def test_doctor_does_not_call_a_foreign_garmin_server_ours(tmp_path):
    deps, _ = make_deps(tmp_path, which=CLAUDE_WHICH, run=FakeRun(listing=FOREIGN_LISTING))
    with respx.mock:
        main(["doctor"], deps)
    assert "not garmin-dynamic-mcp" in output(deps)


def test_doctor_does_not_mistake_a_lookalike_name_for_ours(tmp_path):
    deps, _ = make_deps(tmp_path, which=CLAUDE_WHICH, run=FakeRun(listing=LOOKALIKE_LISTING))
    with respx.mock:
        main(["doctor"], deps)
    assert "garmin is not registered" in output(deps)


def test_update_leaves_a_foreign_cli_server_alone(tmp_path):
    run = FakeRun(listing=FOREIGN_LISTING)
    deps, _ = make_deps(tmp_path, which=CLAUDE_WHICH, run=run)
    assert main(["update"], deps) == 0
    assert run.mutations() == []
