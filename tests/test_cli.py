import io
import json
import subprocess
import time
from datetime import datetime

import httpx
import keyring
import pytest
import respx
from conftest import make_jwt

from garmin_dynamic_mcp import cli
from garmin_dynamic_mcp.auth import KEY_PAGE, TOKEN_URL
from garmin_dynamic_mcp.cli import Deps, main
from garmin_dynamic_mcp.keystore import ACCOUNT, SERVICE, fallback_path
from garmin_dynamic_mcp.updates import PYPI_URL
from garmin_dynamic_mcp.version import __version__

KEY = "test-key"
UVX = "/u/bin/uvx"
DAY = 24 * 3600


class Recorder:
    def __init__(self):
        self.opened = []
        self.cleared = []
        self.asked = []
        self.runs = []


def make_deps(tmp_path, *, secrets=("",), clipboard=f"  {KEY}\n", answers=None, which=None, stdin="", **extra):
    rec = Recorder()
    secret_queue = list(secrets)
    answer_queue = list(answers or [])

    def getpass(_prompt):
        return secret_queue.pop(0) if secret_queue else ""

    def ask(prompt):
        rec.asked.append(prompt)
        return answer_queue.pop(0) if answer_queue else "y"

    def open_browser(url):
        rec.opened.append(url)
        return True

    def clear(value):
        rec.cleared.append(value)
        return True

    def run(argv, **kwargs):
        rec.runs.append(argv)
        stdout = "garmin: uvx garmin-dynamic-mcp\n" if argv[-1] == "list" else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    deps = Deps(
        stdin_isatty=lambda: False,
        read_stdin=lambda: stdin,
        getpass=getpass,
        ask=ask,
        out=io.StringIO(),
        err=io.StringIO(),
        open_browser=open_browser,
        read_clipboard=lambda: clipboard,
        clear_clipboard_if=clear,
        which=which or (lambda name: UVX if name == "uvx" else None),
        run=run,
        home=home,
        platform="darwin",
        environ={"GARMIN_MCP_NO_UPDATE_CHECK": "1"},
        http_factory=lambda: httpx.AsyncClient(),
        now=lambda: datetime(2026, 11, 10, 12, 0, 0),
    )
    for name, value in extra.items():
        setattr(deps, name, value)
    return deps, rec


def desktop_config(deps):
    return deps.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def cursor_config(deps):
    return deps.home / ".cursor" / "mcp.json"


def output(deps):
    return deps.out.getvalue() + deps.err.getvalue()


def token_ok(lifetime=DAY):
    now = int(time.time())
    return respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=make_jwt(now, now + lifetime)))


@respx.mock
def test_setup_happy_path_reads_clipboard_and_configures_claude_desktop(tmp_path):
    token_ok()
    deps, rec = make_deps(tmp_path)
    desktop_config(deps).parent.mkdir(parents=True)
    assert main(["setup"], deps) == 0
    assert keyring.get_password(SERVICE, ACCOUNT) == KEY
    assert rec.opened == [KEY_PAGE] and rec.cleared == [KEY]
    entry = json.loads(desktop_config(deps).read_text(encoding="utf-8"))["mcpServers"]["garmin"]
    assert entry == {"command": UVX, "args": [f"garmin-dynamic-mcp=={__version__}"]}
    text = output(deps)
    assert KEY not in text
    assert KEY_PAGE in text and "Restart" in text


@respx.mock
def test_setup_pasted_key_is_used_and_clipboard_not_cleared(tmp_path):
    token_ok()
    deps, rec = make_deps(tmp_path, secrets=[" pasted-key "], clipboard="something else")
    assert main(["setup", "--clients", "none"], deps) == 0
    assert keyring.get_password(SERVICE, ACCOUNT) == "pasted-key"
    assert rec.cleared == []


@respx.mock
def test_setup_rejected_key_asks_again_and_stores_only_the_good_one(tmp_path):
    respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(200, text=make_jwt(int(time.time()), int(time.time()) + DAY)),
        ]
    )
    deps, _ = make_deps(tmp_path, secrets=["bad-key", "good-key"])
    assert main(["setup", "--clients", "none"], deps) == 0
    assert keyring.get_password(SERVICE, ACCOUNT) == "good-key"
    assert "expired or was revoked" in output(deps)


@respx.mock
def test_setup_gives_up_after_three_bad_keys(tmp_path):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401))
    deps, _ = make_deps(tmp_path, secrets=["k1", "k2", "k3"])
    assert main(["setup", "--clients", "none"], deps) == 1
    assert keyring.get_password(SERVICE, ACCOUNT) is None


def test_setup_without_uvx_stops_with_install_hint(tmp_path):
    deps, _ = make_deps(tmp_path, which=lambda _name: None)
    assert main(["setup"], deps) == 1
    assert "astral.sh/uv" in output(deps)
    assert keyring.get_password(SERVICE, ACCOUNT) is None


@respx.mock
def test_setup_no_keychain_needs_allow_file_storage(tmp_path, no_keychain):
    token_ok()
    deps, _ = make_deps(tmp_path)
    assert main(["setup", "--clients", "none"], deps) == 1
    assert not fallback_path(deps.home).exists()
    assert "--allow-file-storage" in output(deps)

    deps, _ = make_deps(tmp_path)
    assert main(["setup", "--clients", "none", "--allow-file-storage"], deps) == 0
    assert fallback_path(deps.home).read_text(encoding="utf-8").strip() == KEY


@respx.mock
def test_setup_twice_is_idempotent(tmp_path):
    token_ok()
    deps, _ = make_deps(tmp_path)
    desktop_config(deps).parent.mkdir(parents=True)
    assert main(["setup", "--yes"], deps) == 0
    deps2, _ = make_deps(tmp_path)
    assert main(["setup", "--yes"], deps2) == 0
    assert "unchanged" in output(deps2)


@respx.mock
def test_setup_noninteractive_with_explicit_clients(tmp_path):
    token_ok()
    deps, rec = make_deps(tmp_path, stdin=f"{KEY}\n")
    assert main(["setup", "--key-stdin", "--clients", "cursor,vscode", "--yes"], deps) == 0
    assert rec.opened == [] and rec.asked == []
    assert json.loads(cursor_config(deps).read_text(encoding="utf-8"))["mcpServers"]["garmin"]["type"] == "stdio"
    vscode = deps.home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    assert "garmin" in json.loads(vscode.read_text(encoding="utf-8"))["servers"]


@respx.mock
def test_setup_prints_snippet_for_unparseable_config(tmp_path):
    token_ok()
    deps, _ = make_deps(tmp_path)
    cursor_config(deps).parent.mkdir(parents=True)
    cursor_config(deps).write_text("{ // my comments\n}", encoding="utf-8")
    assert main(["setup", "--clients", "cursor", "--yes"], deps) == 0
    assert '"garmin"' in output(deps)
    assert cursor_config(deps).read_text(encoding="utf-8") == "{ // my comments\n}"


@respx.mock
def test_setup_unknown_client_id_is_an_error(tmp_path):
    deps, _ = make_deps(tmp_path)
    assert main(["setup", "--clients", "notepad"], deps) == 2
    assert "notepad" in output(deps)


@respx.mock
def test_setup_registers_claude_code_through_its_cli(tmp_path):
    token_ok()
    which = {"uvx": UVX, "claude": "/u/bin/claude"}.get
    deps, rec = make_deps(tmp_path, which=which)
    assert main(["setup", "--clients", "claude-code", "--yes"], deps) == 0
    assert rec.runs[-1][:3] == ["/u/bin/claude", "mcp", "add"]


@respx.mock
def test_doctor_all_green_exit_0_and_never_prints_key(tmp_path):
    token_ok()
    respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": __version__}}))
    keyring.set_password(SERVICE, ACCOUNT, KEY)
    deps, _ = make_deps(tmp_path)
    desktop_config(deps).parent.mkdir(parents=True)
    desktop_config(deps).write_text(
        json.dumps({"mcpServers": {"garmin": {"command": UVX, "args": [f"garmin-dynamic-mcp=={__version__}"]}}}),
        encoding="utf-8",
    )
    assert main(["doctor"], deps) == 0
    text = output(deps)
    assert KEY not in text and "FAIL" not in text
    assert "keychain" in text and "Claude Desktop" in text


def test_doctor_missing_key_exit_1(tmp_path):
    deps, _ = make_deps(tmp_path)
    with respx.mock:
        respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": __version__}}))
        assert main(["doctor"], deps) == 1
    assert "FAIL" in output(deps) and "setup" in output(deps)


@respx.mock
def test_doctor_warns_about_newer_release(tmp_path):
    token_ok()
    respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "99.0.0"}}))
    keyring.set_password(SERVICE, ACCOUNT, KEY)
    deps, _ = make_deps(tmp_path)
    assert main(["doctor"], deps) == 0
    assert "99.0.0" in output(deps) and "WARN" in output(deps)


def test_update_rewrites_pins_only_for_our_entries(tmp_path):
    deps, _ = make_deps(tmp_path)
    cursor_config(deps).parent.mkdir(parents=True)
    ours = {"type": "stdio", "command": "/old/uvx", "args": ["garmin-dynamic-mcp==0.1.9"]}
    cursor_config(deps).write_text(json.dumps({"mcpServers": {"garmin": ours}}), encoding="utf-8")
    desktop_config(deps).parent.mkdir(parents=True)
    foreign = {"command": "npx", "args": ["someone-elses-garmin"]}
    desktop_config(deps).write_text(json.dumps({"mcpServers": {"garmin": foreign}}), encoding="utf-8")
    assert main(["update"], deps) == 0
    updated = json.loads(cursor_config(deps).read_text(encoding="utf-8"))["mcpServers"]["garmin"]
    assert updated == {"type": "stdio", "command": "/old/uvx", "args": [f"garmin-dynamic-mcp=={__version__}"]}
    assert json.loads(desktop_config(deps).read_text(encoding="utf-8"))["mcpServers"]["garmin"] == foreign


def test_forget_removes_key_and_optionally_entries(tmp_path):
    keyring.set_password(SERVICE, ACCOUNT, KEY)
    deps, _ = make_deps(tmp_path)
    cursor_config(deps).parent.mkdir(parents=True)
    cursor_config(deps).write_text(
        json.dumps({"mcpServers": {"garmin": {"command": UVX, "args": ["garmin-dynamic-mcp==0.2.0"]}}}),
        encoding="utf-8",
    )
    assert main(["forget"], deps) == 0
    assert keyring.get_password(SERVICE, ACCOUNT) is None
    assert "garmin" in json.loads(cursor_config(deps).read_text(encoding="utf-8"))["mcpServers"]
    assert main(["forget", "--clients", "all"], deps) == 0
    assert json.loads(cursor_config(deps).read_text(encoding="utf-8"))["mcpServers"] == {}


def test_no_subcommand_on_tty_prints_hint_then_serves(tmp_path, monkeypatch):
    served = []
    monkeypatch.setattr(cli, "serve", lambda: served.append(True))
    deps, _ = make_deps(tmp_path, stdin_isatty=lambda: True)
    assert main([], deps) == 0
    assert served == [True] and "uvx garmin-dynamic-mcp setup" in deps.err.getvalue()


def test_no_subcommand_from_a_client_serves_silently(tmp_path, monkeypatch):
    served = []
    monkeypatch.setattr(cli, "serve", lambda: served.append(True))
    deps, _ = make_deps(tmp_path)
    assert main([], deps) == 0
    assert served == [True] and deps.err.getvalue() == ""


def test_version_flag(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"], make_deps(tmp_path)[0])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out
