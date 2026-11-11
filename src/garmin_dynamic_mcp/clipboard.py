"""Read (and clear) the clipboard with the tools each OS already has. No extra dependency.

Every failure returns None/False: setup then falls back to the hidden prompt.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable

Which = Callable[[str], str | None]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]

_POWERSHELL = ("powershell", "pwsh")
_LINUX_READERS = (
    ("wl-paste", ["--no-newline"]),
    ("xclip", ["-selection", "clipboard", "-o"]),
    ("xsel", ["--clipboard", "--output"]),
)
_LINUX_WRITERS = {
    "wl-paste": ("wl-copy", ["--clear"]),
    "xclip": ("xclip", ["-selection", "clipboard", "-i"]),
    "xsel": ("xsel", ["--clipboard", "--input"]),
}


def _first(which: Which, names: tuple[str, ...]) -> str | None:
    for name in names:
        path = which(name)
        if path:
            return path
    return None


def _run(run: Runner, argv: list[str], stdin: str | None = None) -> str | None:
    try:
        result = run(argv, input=stdin, capture_output=True, text=True, timeout=10, check=False, shell=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def read_clipboard(
    *, platform: str = sys.platform, which: Which = shutil.which, run: Runner = subprocess.run
) -> str | None:
    if platform == "win32":
        shell = _first(which, _POWERSHELL)
        return _run(run, [shell, "-NoProfile", "-Command", "Get-Clipboard -Raw"]) if shell else None
    if platform == "darwin":
        tool = which("pbpaste")
        return _run(run, [tool]) if tool else None
    for name, args in _LINUX_READERS:
        tool = which(name)
        if tool:
            return _run(run, [tool, *args])
    return None


def _clear(platform: str, which: Which, run: Runner) -> bool:
    if platform == "win32":
        shell = _first(which, _POWERSHELL)
        if shell is None:
            return False
        return _run(run, [shell, "-NoProfile", "-Command", "Set-Clipboard -Value ' '"]) is not None
    if platform == "darwin":
        tool = which("pbcopy")
        return tool is not None and _run(run, [tool], stdin="") is not None
    for reader, _args in _LINUX_READERS:
        if which(reader):
            name, args = _LINUX_WRITERS[reader]
            writer = which(name)
            return writer is not None and _run(run, [writer, *args], stdin="") is not None
    return False


def clear_clipboard_if(
    value: str, *, platform: str = sys.platform, which: Which = shutil.which, run: Runner = subprocess.run
) -> bool:
    """Clear the clipboard, but only if it still holds `value` (the user may have copied something else)."""
    current = read_clipboard(platform=platform, which=which, run=run)
    if current is None or current.replace("﻿", "").strip().strip("\"'").strip() != value:
        return False
    return _clear(platform, which, run)
