import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from garmin_dynamic_mcp.clients import (
    ClientSpec,
    configure_cli,
    detected_paths,
    generic_snippet,
    is_detected,
    is_ours,
    known_clients,
    pinned_version,
    read_json_entry,
    remove_cli,
    remove_json_entry,
    server_entry,
    write_json_entry,
)

UVX = "C:\\Users\\Name Surname\\.local\\bin\\uvx.exe"
ENTRY = server_entry(UVX, "0.2.0")
NOW = lambda: datetime(2026, 11, 10, 12, 0, 0)  # noqa: E731
NEVER = lambda _existing: False  # noqa: E731
ALWAYS = lambda _existing: True  # noqa: E731


def _write(path: Path, root="mcpServers", entry=ENTRY, confirm=NEVER):
    return write_json_entry("Test", path, root, entry, confirm_replace=confirm, now=NOW)


def test_server_entry_is_pinned_and_has_no_env():
    assert ENTRY == {"command": UVX, "args": ["garmin-dynamic-mcp==0.2.0"]}
    assert server_entry("uvx", "0.2.0", {"type": "stdio"}) == {
        "type": "stdio",
        "command": "uvx",
        "args": ["garmin-dynamic-mcp==0.2.0"],
    }


def test_is_ours_and_pinned_version():
    assert is_ours(ENTRY) and pinned_version(ENTRY) == "0.2.0"
    foreign = {"command": "npx", "args": ["other-garmin-server"]}
    assert not is_ours(foreign) and pinned_version(foreign) is None


def test_writes_new_file(tmp_path):
    path = tmp_path / "cfg.json"
    result = _write(path)
    assert result.status == "written" and result.path == path
    assert json.loads(path.read_text(encoding="utf-8")) == {"mcpServers": {"garmin": ENTRY}}


@pytest.mark.parametrize("content", ["", "  \n"])
def test_empty_file_is_treated_as_empty_object(tmp_path, content):
    path = tmp_path / "cfg.json"
    path.write_text(content, encoding="utf-8")
    assert _write(path).status == "written"
    assert json.loads(path.read_text(encoding="utf-8")) == {"mcpServers": {"garmin": ENTRY}}


def test_keeps_other_servers_and_key_order(tmp_path):
    path = tmp_path / "cfg.json"
    original = {"theme": "dark", "mcpServers": {"a": {"command": "x"}}, "other": 1}
    path.write_text(json.dumps(original), encoding="utf-8")
    _write(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(data) == ["theme", "mcpServers", "other"]
    assert list(data["mcpServers"]) == ["a", "garmin"] and data["mcpServers"]["a"] == {"command": "x"}


@pytest.mark.parametrize("content", ['{ // comment\n "servers": {} }', "{not json", "[]", '{"mcpServers": []}'])
def test_unparseable_or_unexpected_files_are_never_written(tmp_path, content):
    path = tmp_path / "cfg.json"
    path.write_text(content, encoding="utf-8")
    result = _write(path)
    assert result.status == "snippet"
    assert '"garmin"' in result.detail
    assert path.read_text(encoding="utf-8") == content
    assert list(tmp_path.glob("cfg.json?*")) == []  # no backup, no temp file


def test_backup_created_once(tmp_path):
    path = tmp_path / "claude_desktop_config.json"
    path.write_text('{"mcpServers": {}}', encoding="utf-8")
    _write(path)
    backups = list(tmp_path.glob("claude_desktop_config.json.bak-garmin-*"))
    assert [b.name for b in backups] == ["claude_desktop_config.json.bak-garmin-20261110120000"]
    assert backups[0].read_text(encoding="utf-8") == '{"mcpServers": {}}'
    _write(path, entry=server_entry(UVX, "0.3.0"))
    assert len(list(tmp_path.glob("*.bak-garmin-*"))) == 1


def test_no_backup_for_new_file(tmp_path):
    _write(tmp_path / "cfg.json")
    assert list(tmp_path.glob("*.bak-garmin-*")) == []


def test_same_entry_is_unchanged(tmp_path):
    path = tmp_path / "cfg.json"
    _write(path)
    before = path.stat().st_mtime_ns
    assert _write(path).status == "unchanged"
    assert path.stat().st_mtime_ns == before


def test_our_older_entry_is_replaced_without_asking(tmp_path):
    path = tmp_path / "cfg.json"
    _write(path, entry=server_entry(UVX, "0.1.0"))
    assert _write(path, confirm=NEVER).status == "written"
    assert pinned_version(read_json_entry(path, "mcpServers")) == "0.2.0"


def test_foreign_garmin_entry_needs_confirmation(tmp_path):
    path = tmp_path / "cfg.json"
    foreign = {"mcpServers": {"garmin": {"command": "npx", "args": ["someone-else"]}}}
    path.write_text(json.dumps(foreign), encoding="utf-8")
    assert _write(path, confirm=NEVER).status == "skipped"
    assert json.loads(path.read_text(encoding="utf-8")) == foreign
    assert _write(path, confirm=ALWAYS).status == "written"


def test_vscode_uses_servers_and_type_stdio(tmp_path):
    path = tmp_path / "mcp.json"
    _write(path, root="servers", entry=server_entry(UVX, "0.2.0", {"type": "stdio"}))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["servers"]["garmin"]["type"] == "stdio"


def test_uvx_path_with_spaces_kept_as_one_string(tmp_path):
    path = tmp_path / "cfg.json"
    _write(path)
    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["garmin"]["command"] == UVX


def test_remove_entry(tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"mcpServers": {"a": {}, "garmin": ENTRY}}), encoding="utf-8")
    assert remove_json_entry("Test", path, "mcpServers").status == "removed"
    assert json.loads(path.read_text(encoding="utf-8")) == {"mcpServers": {"a": {}}}
    assert remove_json_entry("Test", path, "mcpServers").status == "unchanged"


def test_read_json_entry_tolerates_missing_and_broken_files(tmp_path):
    assert read_json_entry(tmp_path / "missing.json", "mcpServers") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert read_json_entry(broken, "mcpServers") is None


class FakeRun:
    def __init__(self, returncode=0, stderr="", listing=""):
        self.calls = []
        self.kwargs = []
        self.returncode = returncode
        self.stderr = stderr
        self.listing = listing

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        self.kwargs.append(kwargs)
        if argv[1:3] == ["mcp", "get"]:  # exit 0 + details when the server exists, exit 1 when it does not
            return subprocess.CompletedProcess(argv, 0 if self.listing else 1, stdout=self.listing, stderr="")
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr=self.stderr)

    def mutations(self):
        return [c for c in self.calls if c[1:3] != ["mcp", "get"]]


CLAUDE = ClientSpec(id="claude-code", name="Claude Code", kind="cli", cli="claude")
CODEX = ClientSpec(id="codex", name="Codex CLI", kind="cli", cli="codex")


def test_claude_code_uses_argv_without_shell():
    run = FakeRun()
    result = configure_cli(CLAUDE, UVX, "0.2.0", run, which=lambda name: f"/bin/{name}")
    assert result.status == "written"
    assert run.mutations()[0] == ["/bin/claude", "mcp", "remove", "garmin", "--scope", "user"]
    assert run.mutations()[1] == [
        "/bin/claude",
        "mcp",
        "add",
        "--scope",
        "user",
        "--transport",
        "stdio",
        "garmin",
        "--",
        UVX,
        "garmin-dynamic-mcp==0.2.0",
    ]
    assert all(not kw.get("shell") for kw in run.kwargs)


def test_codex_add_command():
    run = FakeRun()
    configure_cli(CODEX, UVX, "0.2.0", run, which=lambda name: f"/bin/{name}")
    assert run.mutations()[1] == ["/bin/codex", "mcp", "add", "garmin", "--", UVX, "garmin-dynamic-mcp==0.2.0"]


def test_cli_failure_reports_error_without_raising():
    run = FakeRun(returncode=1, stderr="boom happened\nmore")
    result = configure_cli(CLAUDE, UVX, "0.2.0", run, which=lambda name: f"/bin/{name}")
    assert result.status == "error" and "boom happened" in result.detail


def test_cli_missing_binary_is_skipped():
    result = configure_cli(CLAUDE, UVX, "0.2.0", FakeRun(), which=lambda _name: None)
    assert result.status == "skipped"


def test_remove_cli():
    run = FakeRun()
    assert remove_cli(CLAUDE, run, which=lambda name: f"/bin/{name}").status == "removed"
    assert run.mutations() == [["/bin/claude", "mcp", "remove", "garmin", "--scope", "user"]]


def test_known_clients_windows_paths(tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    clients = {c.id: c for c in known_clients(tmp_path, "win32", {"APPDATA": str(appdata)})}
    assert set(clients) == {"claude-desktop", "claude-code", "cursor", "vscode", "windsurf", "gemini", "codex"}
    assert clients["claude-desktop"].paths == (appdata / "Claude" / "claude_desktop_config.json",)
    assert clients["vscode"].paths == (appdata / "Code" / "User" / "mcp.json",)
    assert clients["vscode"].root_key == "servers"
    assert clients["cursor"].paths == (tmp_path / ".cursor" / "mcp.json",)


def test_known_clients_macos_paths(tmp_path):
    clients = {c.id: c for c in known_clients(tmp_path, "darwin", {})}
    support = tmp_path / "Library" / "Application Support"
    assert clients["claude-desktop"].paths == (support / "Claude" / "claude_desktop_config.json",)
    assert clients["vscode"].paths == (support / "Code" / "User" / "mcp.json",)


def test_detection_by_directory_or_file(tmp_path):
    clients = {c.id: c for c in known_clients(tmp_path, "darwin", {})}
    no_cli = lambda _name: None  # noqa: E731
    assert not is_detected(clients["cursor"], no_cli)
    (tmp_path / ".cursor").mkdir()
    assert detected_paths(clients["cursor"], no_cli) == [tmp_path / ".cursor" / "mcp.json"]
    (tmp_path / ".gemini").mkdir()
    assert not is_detected(clients["gemini"], no_cli)  # Gemini needs the settings file itself
    (tmp_path / ".gemini" / "settings.json").write_text("{}", encoding="utf-8")
    assert is_detected(clients["gemini"], no_cli)
    assert is_detected(clients["claude-code"], lambda name: "/bin/claude" if name == "claude" else None)


def test_windsurf_writes_only_existing_files(tmp_path):
    clients = {c.id: c for c in known_clients(tmp_path, "linux", {})}
    legacy = tmp_path / ".codeium" / "windsurf" / "mcp_config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}", encoding="utf-8")
    assert detected_paths(clients["windsurf"], lambda _n: None) == [legacy]


def test_generic_snippet():
    snippet = json.loads(generic_snippet(UVX, "0.2.0"))
    assert snippet == {"mcpServers": {"garmin": ENTRY}}
