"""Regression tests for the findings of the whole-branch review (CLI behavior)."""

import io
import time

import httpx
import respx
from keyring.errors import KeyringLocked, PasswordSetError
from test_cli import KEY, UVX, cursor_config, desktop_config, make_deps, output, token_ok
from test_clients import FakeRun
from test_clients_review import FOREIGN_LISTING, LOOKALIKE_LISTING

from garmin_dynamic_mcp import cli
from garmin_dynamic_mcp.auth import TOKEN_URL
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


# --- clearer key entry and progress feedback ----------------------------------------------------


class _FakeTty(io.StringIO):
    def isatty(self):
        return True


@respx.mock
def test_setup_prompt_says_that_enter_uses_the_clipboard(tmp_path):
    token_ok()
    prompts = []

    def getpass(prompt):
        prompts.append(prompt)
        return ""

    deps, _ = make_deps(tmp_path)
    deps.getpass = getpass
    assert main(["setup", "--clients", "none"], deps) == 0
    assert "Enter" in prompts[0] and "clipboard" in prompts[0] and "paste" in prompts[0].lower()
    assert "Copy" in deps.out.getvalue()  # the instructions name the Copy button on Garmin's page


@respx.mock
def test_setup_reports_how_many_characters_it_read_from_the_clipboard(tmp_path):
    token_ok()
    deps, _ = make_deps(tmp_path)  # clipboard holds "  test-key\n": 8 characters once cleaned
    assert main(["setup", "--clients", "none"], deps) == 0
    assert f"Read {len(KEY)} characters from the clipboard" in output(deps)
    assert KEY not in output(deps)


@respx.mock
def test_pasted_key_with_control_characters_is_cleaned_before_it_is_sent(tmp_path):
    route = token_ok()
    deps, _ = make_deps(tmp_path, secrets=["\x16test-key\x16"])
    assert main(["setup", "--clients", "none"], deps) == 0
    assert route.calls.last.request.headers["Authorization"] == f"ApiKey {KEY}"
    assert f"Received {len(KEY)} characters" in output(deps)


@respx.mock
def test_rejected_key_message_gives_its_length_and_suggests_the_clipboard(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401))
    deps, _ = make_deps(tmp_path, secrets=["short-key", "short-key", "short-key"])
    assert main(["setup", "--clients", "none"], deps) == 1
    text = output(deps)
    assert "9 characters" in text and "clipboard" in text and "short-key" not in text


@respx.mock
def test_setup_announces_each_client_before_working_on_it(tmp_path):
    token_ok()
    deps, _ = make_deps(tmp_path)
    desktop_config(deps).parent.mkdir(parents=True)
    assert main(["setup", "--clients", "claude-desktop", "--yes"], deps) == 0
    text = output(deps)
    assert text.index("Configuring Claude Desktop") < text.index("Claude Desktop - written")


def test_working_prints_one_line_without_a_terminal(tmp_path):
    deps, _ = make_deps(tmp_path)
    with cli._working(deps, "Checking the key with Garmin"):
        pass
    assert deps.out.getvalue() == "  ... Checking the key with Garmin\n"


def test_working_animates_and_cleans_up_on_a_terminal(tmp_path):
    deps, _ = make_deps(tmp_path)
    deps.out = _FakeTty()
    with cli._working(deps, "Configuring Claude Code"):
        time.sleep(0.25)
    shown = deps.out.getvalue()
    assert "Configuring Claude Code" in shown and shown.endswith("\r")
    assert shown.count("\r") >= 2  # redrawn at least once, then cleared
