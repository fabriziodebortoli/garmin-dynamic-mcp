"""Print the CHANGELOG.md section of one version (used as the GitHub Release notes).

Usage: python scripts/changelog_section.py CHANGELOG.md 0.2.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def changelog_section(text: str, version: str) -> str:
    """The body under '## [version]' up to the next '## [' heading or the link references."""
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(text)
    if not match:
        raise ValueError(f"CHANGELOG has no section for version {version}")
    rest = text[match.end() :]
    end = re.search(r"^(## \[|\[[^\]]+\]: )", rest, re.MULTILINE)
    return (rest[: end.start()] if end else rest).strip()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: python scripts/changelog_section.py CHANGELOG.md VERSION", file=sys.stderr)
        return 2
    try:
        print(changelog_section(Path(argv[1]).read_text(encoding="utf-8"), argv[2]))
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
