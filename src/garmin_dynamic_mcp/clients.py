"""Write the `garmin` server entry into MCP client configurations, safely.

Rules: never write a file that is not strict JSON with the expected shape (print a snippet instead),
back the file up once before the first change, touch only the `garmin` entry, write atomically,
and ask before replacing a `garmin` entry that someone else created.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

SERVER_NAME = "garmin"
PACKAGE = "garmin-dynamic-mcp"

Status = Literal["written", "unchanged", "skipped", "snippet", "removed", "error"]
Which = Callable[[str], str | None]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class ClientSpec:
    id: str
    name: str
    kind: Literal["json", "cli"]
    paths: tuple[Path, ...] = ()
    root_key: str = "mcpServers"
    entry_extra: Mapping[str, str] = field(default_factory=dict)
    cli: str | None = None
    require_file: bool = False


@dataclass
class WriteResult:
    client: str
    status: Status
    detail: str
    path: Path | None = None


def known_clients(home: Path, platform: str, environ: Mapping[str, str]) -> list[ClientSpec]:
    if platform == "win32":
        appdata = Path(environ.get("APPDATA") or home / "AppData" / "Roaming")
        desktop, desktop_needs_file = appdata / "Claude" / "claude_desktop_config.json", False
        vscode = appdata / "Code" / "User" / "mcp.json"
    elif platform == "darwin":
        support = home / "Library" / "Application Support"
        desktop, desktop_needs_file = support / "Claude" / "claude_desktop_config.json", False
        vscode = support / "Code" / "User" / "mcp.json"
    else:
        desktop, desktop_needs_file = home / ".config" / "Claude" / "claude_desktop_config.json", True
        vscode = home / ".config" / "Code" / "User" / "mcp.json"
    stdio = {"type": "stdio"}
    return [
        ClientSpec("claude-desktop", "Claude Desktop", "json", (desktop,), require_file=desktop_needs_file),
        ClientSpec("claude-code", "Claude Code", "cli", cli="claude"),
        ClientSpec("cursor", "Cursor", "json", (home / ".cursor" / "mcp.json",), entry_extra=stdio),
        ClientSpec("vscode", "VS Code", "json", (vscode,), root_key="servers", entry_extra=stdio),
        ClientSpec(
            "windsurf",
            "Windsurf / Devin Desktop",
            "json",
            (
                home / ".codeium" / "windsurf" / "mcp_config.json",
                home / ".codeium" / "mcp_config.json",
                home / ".config" / "devin" / "mcp_config.json",
            ),
            require_file=True,
        ),
        ClientSpec("gemini", "Gemini CLI", "json", (home / ".gemini" / "settings.json",), require_file=True),
        ClientSpec("codex", "Codex CLI", "cli", cli="codex"),
    ]


def detected_paths(spec: ClientSpec, which: Which) -> list[Path]:
    if spec.kind != "json":
        return []
    return [p for p in spec.paths if p.is_file() or (not spec.require_file and p.parent.is_dir())]


def is_detected(spec: ClientSpec, which: Which) -> bool:
    if spec.kind == "cli":
        return spec.cli is not None and which(spec.cli) is not None
    return bool(detected_paths(spec, which))


def server_entry(uvx: str, version: str, extra: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {**(extra or {}), "command": uvx, "args": [f"{PACKAGE}=={version}"]}


def is_ours(entry: Mapping[str, Any]) -> bool:
    args = entry.get("args") or []
    return isinstance(args, list) and any(isinstance(a, str) and a.startswith(PACKAGE) for a in args)


def pinned_version(entry: Mapping[str, Any] | None) -> str | None:
    if not entry or not is_ours(entry):
        return None
    for arg in entry.get("args") or []:
        if isinstance(arg, str) and arg.startswith(f"{PACKAGE}=="):
            return arg.split("==", 1)[1]
    return None


def generic_snippet(
    uvx: str, version: str, root_key: str = "mcpServers", extra: Mapping[str, str] | None = None
) -> str:
    return json.dumps({root_key: {SERVER_NAME: server_entry(uvx, version, extra)}}, indent=2, ensure_ascii=False)


def _load(path: Path, root_key: str) -> dict[str, Any] | None:
    """The parsed file ({} if missing or empty), or None if it must not be touched."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")  # tolerates the BOM that Notepad and PowerShell 5 write
    except UnicodeDecodeError:
        return None  # UTF-16 or a legacy code page: not ours to rewrite
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get(root_key, {}), dict):
        return None
    return data


def read_json_entry(path: Path, root_key: str) -> dict[str, Any] | None:
    try:
        data = _load(path, root_key)
    except OSError:
        return None
    if not data:
        return None
    entry = data.get(root_key, {}).get(SERVER_NAME)
    return entry if isinstance(entry, dict) else None


def _real(path: Path) -> Path:
    """Follow a symlink (dotfile managers) so the link survives and the real file is the one rewritten."""
    return path.resolve() if path.is_symlink() else path


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    real = _real(path)
    real.parent.mkdir(parents=True, exist_ok=True)
    temp = real.with_name(real.name + ".tmp-garmin")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # private from the first byte
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    if real.exists():
        shutil.copymode(real, temp)  # other servers' tokens often live here: keep the original mode
    os.replace(temp, real)


def _backup_once(path: Path, now: Callable[[], datetime]) -> None:
    real = _real(path)
    if not real.exists() or not real.read_bytes().strip():
        return
    if any(real.parent.glob(f"{real.name}.bak-garmin-*")):
        return
    backup = real.with_name(f"{real.name}.bak-garmin-{now():%Y%m%d%H%M%S}")
    shutil.copy2(real, backup)  # keeps the original permissions


def _merge_own(existing: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """Our own earlier entry updated to `new`: command/type from `new`, only the version pin replaced in args,
    everything else the user added (env, disabled, autoApprove, extra args) kept."""
    merged = dict(existing)
    for key, value in new.items():
        if key != "args":
            merged[key] = value
    pin = next((a for a in (new.get("args") or []) if isinstance(a, str) and a.startswith(PACKAGE)), None)
    raw_old = existing.get("args")
    old_args: list[Any] = list(raw_old) if isinstance(raw_old, list) else []
    if pin is None:
        merged["args"] = list(new.get("args") or old_args)
        return merged
    args: list[Any] = []
    replaced = False
    for arg in old_args:
        if not replaced and isinstance(arg, str) and arg.startswith(PACKAGE):
            args.append(pin)
            replaced = True
        else:
            args.append(arg)
    if not replaced:
        args.append(pin)
    merged["args"] = args
    return merged


def _snippet(client: str, path: Path, root_key: str, entry: dict[str, Any], why: str) -> WriteResult:
    snippet = json.dumps({root_key: {SERVER_NAME: entry}}, indent=2, ensure_ascii=False)
    return WriteResult(client, "snippet", f"{why}. Add this to {path} yourself:\n{snippet}", path)


def write_json_entry(
    client: str,
    path: Path,
    root_key: str,
    entry: dict[str, Any],
    *,
    confirm_replace: Callable[[dict[str, Any]], bool],
    now: Callable[[], datetime] = datetime.now,
) -> WriteResult:
    try:
        data = _load(path, root_key)
    except OSError as err:
        return WriteResult(client, "error", f"cannot read {path} ({type(err).__name__})", path)
    if data is None:
        return _snippet(client, path, root_key, entry, "The file has comments or an unexpected format")
    servers = data.get(root_key, {})
    existing = servers.get(SERVER_NAME)
    if isinstance(existing, dict) and is_ours(existing):
        entry = _merge_own(existing, entry)  # keep the user's env, flags and extra args
    if existing == entry:
        return WriteResult(client, "unchanged", str(path), path)
    if isinstance(existing, dict) and not is_ours(existing) and not confirm_replace(existing):
        return WriteResult(client, "skipped", f"kept the existing 'garmin' entry in {path}", path)
    try:
        _backup_once(path, now)
        data.setdefault(root_key, {})[SERVER_NAME] = entry
        _atomic_write(path, data)
    except OSError as err:
        return WriteResult(client, "error", f"cannot write {path} ({type(err).__name__})", path)
    return WriteResult(client, "written", str(path), path)


def remove_json_entry(client: str, path: Path, root_key: str) -> WriteResult:
    try:
        data = _load(path, root_key)
    except OSError as err:
        return WriteResult(client, "error", f"cannot read {path} ({type(err).__name__})", path)
    if data is None:
        return WriteResult(
            client, "skipped", f"{path} has comments or an unexpected format: remove 'garmin' yourself", path
        )
    if SERVER_NAME not in data.get(root_key, {}):
        return WriteResult(client, "unchanged", str(path), path)
    del data[root_key][SERVER_NAME]
    try:
        _atomic_write(path, data)
    except OSError as err:
        return WriteResult(client, "error", f"cannot write {path} ({type(err).__name__})", path)
    return WriteResult(client, "removed", str(path), path)


def _remove_argv(spec: ClientSpec, binary: str) -> list[str]:
    if spec.id == "claude-code":
        return [binary, "mcp", "remove", SERVER_NAME, "--scope", "user"]
    return [binary, "mcp", "remove", SERVER_NAME]


def _add_argv(spec: ClientSpec, binary: str, uvx: str, version: str) -> list[str]:
    command = [uvx, f"{PACKAGE}=={version}"]
    if spec.id == "claude-code":
        return [binary, "mcp", "add", "--scope", "user", "--transport", "stdio", SERVER_NAME, "--", *command]
    return [binary, "mcp", "add", SERVER_NAME, "--", *command]


def _run(run: Runner, argv: list[str]) -> subprocess.CompletedProcess[str]:
    return run(argv, shell=False, capture_output=True, text=True, timeout=30, check=False)


_LIST_TIMEOUT_S = 90  # `mcp list` health-checks every registered server
_ENTRY_RE = re.compile(rf"\s*{SERVER_NAME}(?=[:\s]|$)")  # exact name: not "garmin-connect", not "garminx"


def _list_servers(run: Runner, binary: str, list_timeout: int = _LIST_TIMEOUT_S) -> str | None:
    """Output of `<cli> mcp list`, or None if it could not be obtained."""
    try:
        result = run(
            [binary, "mcp", "list"], shell=False, capture_output=True, text=True, timeout=list_timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout or "" if result.returncode == 0 else None


def _find_entry(listing: str) -> str | None:
    return next((line.strip() for line in listing.splitlines() if _ENTRY_RE.match(line)), None)


def cli_entry(spec: ClientSpec, run: Runner, which: Which) -> str | None:
    """The `mcp list` line of the server named exactly `garmin`, or None (absent or CLI unavailable)."""
    binary = which(spec.cli) if spec.cli else None
    listing = _list_servers(run, binary) if binary else None
    return _find_entry(listing) if listing is not None else None


def configure_cli(
    spec: ClientSpec,
    uvx: str,
    version: str,
    run: Runner,
    which: Which,
    confirm_replace: Callable[[str], bool] | None = None,
) -> WriteResult:
    binary = which(spec.cli) if spec.cli else None
    if binary is None:
        return WriteResult(spec.name, "skipped", f"'{spec.cli}' is not on PATH")
    listing = _list_servers(run, binary)
    if listing is None:
        return WriteResult(
            spec.name, "error", f"could not run `{spec.cli} mcp list`: add the server yourself (see the README)"
        )
    existing = _find_entry(listing)
    if existing and PACKAGE not in existing and not (confirm_replace and confirm_replace(existing)):
        return WriteResult(spec.name, "skipped", f"kept the existing 'garmin' server in {spec.name}")
    try:
        _run(run, _remove_argv(spec, binary))
        added = _run(run, _add_argv(spec, binary, uvx, version))
    except (OSError, subprocess.SubprocessError) as err:
        return WriteResult(spec.name, "error", f"could not run {spec.cli} ({type(err).__name__})")
    if added.returncode != 0:
        first_line = (added.stderr or added.stdout or "").strip().splitlines()[:1]
        return WriteResult(spec.name, "error", f"{spec.cli} mcp add failed: {' '.join(first_line)}")
    return WriteResult(spec.name, "written", f"registered with `{spec.cli} mcp add`")


def remove_cli(spec: ClientSpec, run: Runner, which: Which) -> WriteResult:
    binary = which(spec.cli) if spec.cli else None
    if binary is None:
        return WriteResult(spec.name, "skipped", f"'{spec.cli}' is not on PATH")
    try:
        result = _run(run, _remove_argv(spec, binary))
    except (OSError, subprocess.SubprocessError) as err:
        return WriteResult(spec.name, "error", f"could not run {spec.cli} ({type(err).__name__})")
    return WriteResult(spec.name, "removed" if result.returncode == 0 else "unchanged", f"`{spec.cli} mcp remove`")
