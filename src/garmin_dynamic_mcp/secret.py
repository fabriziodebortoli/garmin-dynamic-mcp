"""Read a secret from the terminal with visible feedback, so that pasting it visibly works.

The standard `getpass` shows nothing at all, and on Windows it mishandles Ctrl+V. This reader echoes one
`*` per character, understands Ctrl+V (it inserts the clipboard) and backspace, and ignores special keys.
It is used on Windows consoles; other platforms use `getpass`, which handles pasting correctly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TextIO

_ENTER = ("\r", "\n")
_CTRL_C = "\x03"
_CTRL_V = "\x16"
_BACKSPACE = ("\x08", "\x7f")
_SPECIAL_PREFIX = ("\x00", "\xe0")  # arrow and function keys: a second code follows


def read_secret(
    prompt: str,
    *,
    out: TextIO,
    getwch: Callable[[], str],
    read_clipboard: Callable[[], str | None],
) -> str:
    out.write(prompt)
    out.flush()
    chars: list[str] = []
    while True:
        ch = getwch()
        if ch in _ENTER:
            out.write("\n")
            out.flush()
            return "".join(chars)
        if ch == _CTRL_C:
            raise KeyboardInterrupt
        if ch in _SPECIAL_PREFIX:
            getwch()
            continue
        if ch in _BACKSPACE:
            if chars:
                chars.pop()
                out.write("\b \b")
        elif ch == _CTRL_V:
            pasted = (read_clipboard() or "").strip("\r\n")
            chars.extend(pasted)
            out.write("*" * len(pasted))
        else:
            chars.append(ch)
            out.write("*")
        out.flush()
