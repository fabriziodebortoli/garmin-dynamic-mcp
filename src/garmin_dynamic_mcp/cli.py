"""Command line: run the server (default), or set it up, check it, update it, remove it."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import httpx
from keyring.errors import KeyringError

from . import clipboard
from .auth import KEY_PAGE, TokenManager, normalize_key, token_lifetime
from .clients import (
    ClientSpec,
    WriteResult,
    cli_entry,
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
from .errors import GarminError
from .keystore import KeychainUnavailable, delete_key, load_key, save_key
from .secret import read_secret
from .server import serve
from .updates import PYPI_URL, parse_version
from .version import __version__

UV_INSTALL = "https://docs.astral.sh/uv/getting-started/installation/"
_PIN_RE = re.compile(r"garmin-dynamic-mcp==(\d+\.\d+\.\d+)", re.ASCII)
ISSUES_URL = "https://github.com/fabriziodebortoli/garmin-dynamic-mcp/issues"
FIRST_QUESTION = "How many km did I run last week?"
_MAX_ATTEMPTS = 3
_MARK = {
    "written": "[ok]",
    "unchanged": "[ok]",
    "removed": "[ok]",
    "skipped": "[--]",
    "snippet": "[!!]",
    "error": "[!!]",
}


@dataclass
class Deps:
    """Everything the CLI touches outside itself, so tests can replace it."""

    stdin_isatty: Callable[[], bool]
    read_stdin: Callable[[], str]
    getpass: Callable[[str], str]
    ask: Callable[[str], str]
    out: TextIO
    err: TextIO
    open_browser: Callable[[str], bool]
    read_clipboard: Callable[[], str | None]
    clear_clipboard_if: Callable[[str], bool]
    which: Callable[[str], str | None]
    run: Callable[..., Any]
    home: Path
    platform: str
    environ: Mapping[str, str]
    http_factory: Callable[[], httpx.AsyncClient]
    now: Callable[[], datetime]


def _secret_prompt(prompt: str) -> str:
    """Hidden input. On a Windows console use a reader that understands Ctrl+V and shows one * per character."""
    if sys.platform == "win32" and sys.stdin is not None and sys.stdin.isatty():
        import msvcrt

        return read_secret(prompt, out=sys.stdout, getwch=msvcrt.getwch, read_clipboard=clipboard.read_clipboard)
    return getpass.getpass(prompt)


def default_deps() -> Deps:
    return Deps(
        stdin_isatty=lambda: sys.stdin is not None and sys.stdin.isatty(),
        read_stdin=lambda: sys.stdin.read(),
        getpass=_secret_prompt,
        ask=input,
        out=sys.stdout,
        err=sys.stderr,
        open_browser=webbrowser.open,
        read_clipboard=clipboard.read_clipboard,
        clear_clipboard_if=clipboard.clear_clipboard_if,
        which=shutil.which,
        run=subprocess.run,
        home=Path.home(),
        platform=sys.platform,
        environ=os.environ,
        http_factory=lambda: httpx.AsyncClient(timeout=30),
        now=datetime.now,
    )


async def verify_key(key: str, http: httpx.AsyncClient) -> float:
    """Exchange the key for a token; return the token lifetime in seconds. Raises GarminError."""
    return token_lifetime(await TokenManager(key, http).token())


@contextmanager
def _working(deps: Deps, text: str) -> Iterator[None]:
    """Show that something is in progress: one line without a terminal, a small spinner on a terminal."""
    isatty = getattr(deps.out, "isatty", None)
    if not (callable(isatty) and isatty()):
        print(f"  ... {text}", file=deps.out)
        yield
        return
    stop = threading.Event()

    def spin() -> None:
        frames, index = "|/-\\", 0
        while not stop.is_set():
            deps.out.write(f"\r  {frames[index % len(frames)]} {text}")
            deps.out.flush()
            index += 1
            stop.wait(0.1)

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        deps.out.write("\r" + " " * (len(text) + 6) + "\r")
        deps.out.flush()


def _say(deps: Deps, text: str = "") -> None:
    print(text, file=deps.out)


def _yes(deps: Deps, question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return deps.ask(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")
    except EOFError:  # no terminal to ask on (piped input): never guess "yes" about touching a config
        return False


def _clients(deps: Deps) -> list[ClientSpec]:
    return known_clients(deps.home, deps.platform, deps.environ)


def _select_clients(deps: Deps, choice: str | None, assume_yes: bool) -> list[ClientSpec] | None:
    specs = _clients(deps)
    by_id = {s.id: s for s in specs}
    if choice == "none":
        return []
    if choice and choice != "all":
        wanted = [c.strip() for c in choice.split(",") if c.strip()]
        unknown = [c for c in wanted if c not in by_id]
        if unknown:
            print(f"Unknown client: {', '.join(unknown)}. Known: {', '.join(by_id)}, all, none.", file=deps.err)
            return None
        return [by_id[c] for c in wanted]
    detected = [s for s in specs if is_detected(s, deps.which)]
    if choice == "all":
        return detected
    return [s for s in detected if _yes(deps, f"Configure {s.name}?", assume_yes)]


def _print_result(deps: Deps, result: WriteResult) -> None:
    _say(deps, f"  {_MARK[result.status]} {result.client} - {result.status}: {result.detail}")


def _configure(deps: Deps, spec: ClientSpec, uvx: str, assume_yes: bool) -> list[WriteResult]:
    if spec.kind == "cli":

        def confirm_cli(_existing_line: str) -> bool:
            return _yes(deps, f"{spec.name} already has a different 'garmin' server. Replace it?", assume_yes)

        return [configure_cli(spec, uvx, __version__, deps.run, deps.which, confirm_replace=confirm_cli)]
    paths = detected_paths(spec, deps.which) or list(spec.paths[:1])
    entry = server_entry(uvx, __version__, spec.entry_extra)

    def confirm(existing: dict[str, Any]) -> bool:
        return _yes(
            deps,
            f"{spec.name} already has a different 'garmin' server ({existing.get('command')}). Replace it?",
            assume_yes,
        )

    return [
        write_json_entry(spec.name, path, spec.root_key, entry, confirm_replace=confirm, now=deps.now) for path in paths
    ]


def _read_key(deps: Deps, args: argparse.Namespace) -> tuple[str, bool] | None:
    """The normalized key and whether it came from the clipboard; None if there is nothing usable."""
    if args.key_stdin:
        raw, from_clipboard = deps.read_stdin(), False
    else:
        raw = deps.getpass("Press Enter to read the key from your clipboard (or paste it here, hidden): ")
        from_clipboard = not raw.strip()
        if from_clipboard:
            raw = deps.read_clipboard() or ""
            if not raw.strip():
                print(
                    "The clipboard is empty or could not be read: copy the key again with the Copy button on "
                    "Garmin's page, or paste it at the prompt.",
                    file=deps.err,
                )
                return None
    try:
        key = normalize_key(raw)
    except GarminError as err:
        print(err.message, file=deps.err)
        return None
    if not args.key_stdin:
        where = "Read {n} characters from the clipboard." if from_clipboard else "Received {n} characters."
        _say(deps, "  " + where.format(n=len(key)))
    return key, from_clipboard


async def _acquire_key(deps: Deps, args: argparse.Namespace) -> tuple[str, bool] | None:
    attempts = 1 if args.key_stdin else _MAX_ATTEMPTS
    async with deps.http_factory() as http:
        for _ in range(attempts):
            got = _read_key(deps, args)
            if got is None:
                continue
            key, from_clipboard = got
            try:
                with _working(deps, "Checking the key with Garmin"):
                    lifetime = await verify_key(key, http)
            except GarminError as err:
                print(err.message, file=deps.err)
                if err.kind != "key_rejected":
                    return None
                print(
                    f"The key had {len(key)} characters. If you pasted it, try again and just press Enter to use the "
                    "clipboard instead (copy the key with the Copy button on Garmin's page).",
                    file=deps.err,
                )
                continue
            hours = int(lifetime // 3600)
            _say(
                deps, f"  [ok] Garmin accepted the key{'' if hours >= 24 else f' (it expires in about {hours} hours)'}."
            )
            return key, from_clipboard
    return None


async def cmd_setup(deps: Deps, args: argparse.Namespace) -> int:
    selected = _select_clients(deps, args.clients, args.yes) if args.clients else None
    if args.clients and selected is None:
        return 2
    uvx = deps.which("uvx")
    if uvx is None and args.clients != "none":
        print(
            f"uvx was not found on PATH. Install uv first ({UV_INSTALL}), open a new terminal and run setup again.",
            file=deps.err,
        )
        return 1
    _say(deps, "Garmin Dynamic MCP setup")
    if not args.key_stdin:
        _say(deps, "1. Create a Personal API key on Garmin Connect (opening it in your browser):")
        _say(deps, f"   {KEY_PAGE}")
        _say(deps, '2. Click the "Copy" button next to your new key, then come back to this window.')
        deps.open_browser(KEY_PAGE)
    got = await _acquire_key(deps, args)
    if got is None:
        print("No valid key: nothing was saved.", file=deps.err)
        return 1
    key, from_clipboard = got
    try:
        where = save_key(key, allow_file=args.allow_file_storage, home=deps.home)
    except KeyringError as err:  # e.g. a locked or access-denied keychain
        print(
            f"The system keychain refused to store the key ({type(err).__name__}). Unlock it and run setup again, "
            "or use --allow-file-storage.",
            file=deps.err,
        )
        return 1
    except KeychainUnavailable:
        print(
            "No system keychain is available on this machine. To store the key in an owner-only file instead "
            "(~/.config/garmin-dynamic-mcp/api-key), run setup again with --allow-file-storage, "
            "or set GARMIN_API_KEY in your MCP client's configuration.",
            file=deps.err,
        )
        return 1
    _say(deps, f"  [ok] Key saved in the {'system keychain' if where == 'keychain' else 'owner-only file'}.")
    if from_clipboard and deps.clear_clipboard_if(key):
        _say(deps, "  [ok] Clipboard cleared.")
    if selected is None:
        selected = _select_clients(deps, None, args.yes) or []
    if uvx is None or not selected:
        _say(deps, "No MCP client configured. Add this to your client's MCP configuration:")
        _say(deps, generic_snippet(uvx or "uvx", __version__))
        _say(deps, "Tip: run setup with --clients all (or a list such as cursor,vscode) to configure clients.")
    else:
        _say(deps, "Configuring MCP clients:")
        for spec in selected:
            suffix = " (this can take a few seconds)" if spec.kind == "cli" else ""
            with _working(deps, f"Configuring {spec.name}{suffix}"):
                results = _configure(deps, spec, uvx, args.yes)
            for result in results:
                _print_result(deps, result)
    _say(deps)
    _say(deps, f'Restart your MCP client(s), then ask: "{FIRST_QUESTION}"')
    return 0


async def _latest_version(http: httpx.AsyncClient) -> str | None:
    try:
        response = await http.get(PYPI_URL, timeout=5)
        return str(response.json()["info"]["version"]) if response.status_code == 200 else None
    except Exception:  # an unreachable PyPI is a warning, never a crash
        return None


async def cmd_doctor(deps: Deps, _args: argparse.Namespace) -> int:
    failures = 0

    def line(level: str, text: str) -> None:
        nonlocal failures
        failures += level == "FAIL"
        _say(deps, f"{level:<4} {text}")

    _say(deps, f"garmin-dynamic-mcp {__version__}")
    async with deps.http_factory() as http:
        try:
            key, source = load_key(deps.environ, deps.home)
        except GarminError as err:
            line("FAIL", f"Key: {err.message}")
            key = None
        else:
            line("OK", f"Key found ({'environment variable GARMIN_API_KEY' if source == 'env' else source}).")
        if key:
            try:
                hours = int(await verify_key(key, http) // 3600)
            except GarminError as err:
                line("FAIL", f"Garmin: {err.message}")
            else:
                line("WARN" if hours < 24 else "OK", f"Garmin accepted the key (token valid for {hours} h).")
        latest = await _latest_version(http)
    latest_v, current_v = parse_version(latest or ""), parse_version(__version__)
    if latest_v is None:
        line("WARN", "Could not check PyPI for a newer version.")
    elif current_v is not None and latest_v > current_v:
        line("WARN", f"Version {latest} is available. Run: uvx garmin-dynamic-mcp@latest update")
    else:
        line("OK", "Up to date.")
    line(
        "OK" if deps.which("uvx") else "FAIL",
        "uvx is on PATH." if deps.which("uvx") else f"uvx not found: {UV_INSTALL}",
    )
    for spec in _clients(deps):
        if spec.kind == "cli":
            if not (spec.cli and deps.which(spec.cli)):
                continue
            with _working(deps, f"Checking {spec.name}"):
                registered = cli_entry(spec, deps.run, deps.which)
            if registered is None:
                line("WARN", f"{spec.name}: garmin is not registered.")
            elif "garmin-dynamic-mcp" not in registered:
                line("WARN", f"{spec.name}: its 'garmin' server is not garmin-dynamic-mcp.")
            else:
                found = _PIN_RE.search(registered)
                pinned_cli = found.group(1) if found else None
                if pinned_cli == __version__:
                    line("OK", f"{spec.name}: garmin is registered.")
                else:
                    line("WARN", f"{spec.name}: pins version {pinned_cli}. Run: uvx garmin-dynamic-mcp@latest update")
            continue
        for path in detected_paths(spec, deps.which):
            entry = read_json_entry(path, spec.root_key)
            pinned = pinned_version(entry)
            if entry is None:
                line("WARN", f"{spec.name}: not configured ({path}).")
            elif not is_ours(entry):
                line("WARN", f"{spec.name}: its 'garmin' entry is not garmin-dynamic-mcp ({path}).")
            elif pinned != __version__:
                line("WARN", f"{spec.name}: pins version {pinned}. Run: uvx garmin-dynamic-mcp@latest update")
            else:
                line("OK", f"{spec.name}: configured ({path}).")
    return 1 if failures else 0


async def cmd_update(deps: Deps, _args: argparse.Namespace) -> int:
    changed = 0
    for spec in _clients(deps):
        if spec.kind == "cli":
            uvx = deps.which("uvx")
            with _working(deps, f"Checking {spec.name}"):
                registered = cli_entry(spec, deps.run, deps.which) if uvx else None
            if uvx and registered and "garmin-dynamic-mcp" in registered:
                found = _PIN_RE.search(registered)
                if not found or found.group(1) != __version__:
                    _print_result(deps, configure_cli(spec, uvx, __version__, deps.run, deps.which))
                    changed += 1
            continue
        for path in detected_paths(spec, deps.which):
            entry = read_json_entry(path, spec.root_key)
            if not entry or not is_ours(entry) or pinned_version(entry) == __version__:
                continue
            extra = {"type": str(entry["type"])} if "type" in entry else None
            new_entry = server_entry(str(entry.get("command", "uvx")), __version__, extra)
            _print_result(
                deps,
                write_json_entry(
                    spec.name, path, spec.root_key, new_entry, confirm_replace=lambda _e: False, now=deps.now
                ),
            )
            changed += 1
    if changed:
        _say(deps, f"Updated to {__version__}. Restart your MCP client(s).")
    else:
        _say(deps, f"Nothing to update: no client pins an older garmin-dynamic-mcp (running {__version__}).")
    return 0


async def cmd_forget(deps: Deps, args: argparse.Namespace) -> int:
    try:
        removed = delete_key(deps.home)
    except KeyringError as err:
        print(
            f"The system keychain could not be accessed ({type(err).__name__}). Unlock it and try again.",
            file=deps.err,
        )
        return 1
    _say(deps, f"Key removed from: {', '.join(removed)}." if removed else "No stored key found.")
    if args.clients:
        selected = _select_clients(deps, args.clients, True)
        if selected is None:
            return 2
        for spec in selected:
            if spec.kind == "cli":
                _print_result(deps, remove_cli(spec, deps.run, deps.which))
                continue
            for path in detected_paths(spec, deps.which):
                if path.exists():
                    _print_result(deps, remove_json_entry(spec.name, path, spec.root_key))
    _say(deps, f"To revoke the key itself, delete it on Garmin Connect: {KEY_PAGE}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="garmin-dynamic-mcp",
        description="Read-only MCP server for your Garmin Connect data. Without a command, runs the server (stdio).",
    )
    parser.add_argument("--version", action="version", version=f"garmin-dynamic-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")
    setup = sub.add_parser("setup", help="store your Garmin key in the system keychain and configure MCP clients")
    setup.add_argument(
        "--key-stdin", action="store_true", help="read the key from standard input (no prompt, no browser)"
    )
    setup.add_argument("--clients", help="comma-separated client ids, 'all' (detected) or 'none'")
    setup.add_argument("--yes", action="store_true", help="answer yes to every question")
    setup.add_argument(
        "--allow-file-storage",
        action="store_true",
        help="without a system keychain, store the key in an owner-only file",
    )
    sub.add_parser("doctor", help="check the key, the connection to Garmin, the version and client configurations")
    sub.add_parser(
        "update", help="point configured clients to this version (run it with uvx garmin-dynamic-mcp@latest)"
    )
    forget = sub.add_parser("forget", help="delete the stored key (and optionally the client entries)")
    forget.add_argument("--clients", help="also remove the 'garmin' entry: comma-separated ids or 'all'")
    return parser


_COMMANDS = {"setup": cmd_setup, "doctor": cmd_doctor, "update": cmd_update, "forget": cmd_forget}


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    deps = deps or default_deps()
    args = _parser().parse_args(argv)
    if args.command is None:
        if deps.stdin_isatty():
            print("This is an MCP server. To configure it run: uvx garmin-dynamic-mcp setup", file=deps.err)
        serve()
        return 0
    try:
        return asyncio.run(_COMMANDS[args.command](deps, args))
    except KeyboardInterrupt:
        print("\nCancelled.", file=deps.err)
        return 130
    except (OSError, EOFError, KeyringError) as err:  # never a traceback: it could expose paths and context
        print(
            f"Unexpected error ({type(err).__name__}). Run `garmin-dynamic-mcp doctor`, or report it at {ISSUES_URL}",
            file=deps.err,
        )
        return 1


def entry_point() -> None:
    raise SystemExit(main())
