"""Prepare a release for a catalog change: bump the version, add a CHANGELOG entry, write the PR body.

Usage: python scripts/prepare_catalog_release.py OLD_CATALOG NEW_CATALOG
Edits pyproject.toml, server.json (if present) and CHANGELOG.md; writes build/pr_body.md.
Does nothing when the catalogs have no endpoint differences.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from diff_catalog import bump_kind, diff_catalogs, to_markdown

ROOT = Path(__file__).resolve().parent.parent
_VERSION_LINE = re.compile(r'^version = "(\d+\.\d+\.\d+)"$', re.MULTILINE)


def bump_version(version: str, kind: str) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump kind: {kind}")


def add_changelog_entry(changelog: str, version: str, day: str, body: str) -> str:
    marker = "## [Unreleased]"
    if marker not in changelog:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' section")
    entry = f"{marker}\n\n## [{version}] - {day}\n\n{body.strip()}\n"
    return changelog.replace(marker + "\n", entry, 1)


def _set_server_json_version(path: Path, version: str) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    for package in data.get("packages", []):
        package["version"] = version
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: python scripts/prepare_catalog_release.py OLD_CATALOG NEW_CATALOG", file=sys.stderr)
        return 2
    old = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    new = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    diff = diff_catalogs(old, new)
    kind = bump_kind(diff)
    summary = to_markdown(diff)
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = _VERSION_LINE.search(text)
    if not match:
        print("pyproject.toml has no version line", file=sys.stderr)
        return 1
    if kind == "none":
        version = match.group(1)
        print("no endpoint changes: version not bumped")
    else:
        version = bump_version(match.group(1), kind)
        pyproject.write_text(_VERSION_LINE.sub(f'version = "{version}"', text, count=1), encoding="utf-8")
        _set_server_json_version(ROOT / "server.json", version)
        changelog = ROOT / "CHANGELOG.md"
        body = "### Catalog\n\nGarmin changed the Personal API:\n\n" + summary
        changelog.write_text(
            add_changelog_entry(changelog.read_text(encoding="utf-8"), version, date.today().isoformat(), body),
            encoding="utf-8",
        )
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    (build / "pr_body.md").write_text(
        "Garmin's Personal API specification changed. This PR was opened by the daily catalog watcher.\n\n"
        f"**Release:** merging publishes version {version} ({kind} bump).\n\n"
        f"{summary}\n"
        "Review before merging: new endpoints are unverified and become callable by every user "
        "once released. Check that new paths under health categories are classified as sensitive.\n",
        encoding="utf-8",
    )
    print(f"version {version} ({kind})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
