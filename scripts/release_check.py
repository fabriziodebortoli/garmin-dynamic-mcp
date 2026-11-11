"""Decide whether the version in pyproject.toml still needs to be released.

A release is needed when the tag vX.Y.Z does not exist yet on origin. Writes `version=` and `release=`
to $GITHUB_OUTPUT (or prints them when run by hand).

Usage: python scripts/release_check.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_VERSION_LINE = re.compile(r'^version = "(\d+\.\d+\.\d+)"$', re.MULTILINE)


def project_version(pyproject_text: str) -> str:
    match = _VERSION_LINE.search(pyproject_text)
    if not match:
        raise ValueError("pyproject.toml has no 'version = \"X.Y.Z\"' line")
    return match.group(1)


def release_needed(version: str, existing_tags: Iterable[str]) -> bool:
    return f"v{version}" not in set(existing_tags)


def remote_tags() -> list[str]:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", "origin"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return [line.split("refs/tags/", 1)[1] for line in result.stdout.splitlines() if "refs/tags/" in line]


def main() -> int:
    version = project_version((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    needed = release_needed(version, remote_tags())
    lines = [f"version={version}", f"release={'true' if needed else 'false'}"]
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
