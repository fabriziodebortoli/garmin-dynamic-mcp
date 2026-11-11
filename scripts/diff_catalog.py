"""Compare two catalog.json files and describe the differences in Markdown.

Usage: python scripts/diff_catalog.py OLD_CATALOG NEW_CATALOG
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass
class CatalogDiff:
    added: list[str]
    removed: list[str]
    changed: dict[str, list[str]] = field(default_factory=dict)


def _by_path(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["path"]: e for e in catalog.get("endpoints", [])}


def _param_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    old_params = {p["name"]: p for p in old.get("params", [])}
    new_params = {p["name"]: p for p in new.get("params", [])}
    changes = [f"param added: {n}" for n in sorted(set(new_params) - set(old_params))]
    changes += [f"param removed: {n}" for n in sorted(set(old_params) - set(new_params))]
    for name in sorted(set(old_params) & set(new_params)):
        for key in ("location", "required", "type"):
            if old_params[name].get(key) != new_params[name].get(key):
                changes.append(f"param {name} {key}: {old_params[name].get(key)} → {new_params[name].get(key)}")
    return changes


def diff_catalogs(old: dict[str, Any], new: dict[str, Any]) -> CatalogDiff:
    before, after = _by_path(old), _by_path(new)
    result = CatalogDiff(added=sorted(set(after) - set(before)), removed=sorted(set(before) - set(after)))
    for path in sorted(set(before) & set(after)):
        changes = _param_changes(before[path], after[path])
        if before[path].get("max_range_days") != after[path].get("max_range_days"):
            changes.append(
                f"max_range_days: {before[path].get('max_range_days')} → {after[path].get('max_range_days')}"
            )
        if before[path].get("summary") != after[path].get("summary"):
            changes.append("summary changed")
        if changes:
            result.changed[path] = changes
    return result


def bump_kind(diff: CatalogDiff) -> Literal["minor", "patch", "none"]:
    if diff.added or diff.removed:
        return "minor"
    if diff.changed:
        return "patch"
    return "none"


def to_markdown(diff: CatalogDiff) -> str:
    lines: list[str] = []
    if diff.added:
        lines += ["### Added endpoints", "", *[f"- `{p}`" for p in diff.added], ""]
    if diff.removed:
        lines += ["### Removed endpoints", "", *[f"- `{p}`" for p in diff.removed], ""]
    if diff.changed:
        lines += ["### Changed endpoints", ""]
        for path, changes in diff.changed.items():
            lines.append(f"- `{path}`: " + "; ".join(changes))
        lines.append("")
    return "\n".join(lines) if lines else "No endpoint changes (only Garmin's descriptions changed).\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: python scripts/diff_catalog.py OLD_CATALOG NEW_CATALOG", file=sys.stderr)
        return 2
    old = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    new = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    print(to_markdown(diff_catalogs(old, new)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
