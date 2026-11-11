"""Generate src/garmin_dynamic_mcp/catalog.json from Garmin's OpenAPI specification.

Usage:
    python scripts/build_catalog.py build/openapi.json           # write if the spec changed
    python scripts/build_catalog.py build/openapi.json --check   # print "changed" or "unchanged"
    python scripts/build_catalog.py build/openapi.json --force   # rewrite even if unchanged
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SWAGGER_PAGE = "https://developer.garmin.com/gc-developer-program/personal/swagger-docs/"
EXCLUDED_PATHS = {"/download-service/files/activity/{activityId}"}  # .FIT files: phase 2
SENSITIVE_PREFIXES = ("/nutrition-service/", "/periodichealth-service/")
RANGE_PAIRS = (("startDate", "endDate"), ("fromDate", "toDate"), ("fromDate", "untilDate"))
_LIMIT_RE = re.compile(r"maximum of (\d+)\s*(day|days|year|years)\b", re.IGNORECASE)

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "src" / "garmin_dynamic_mcp"
CATALOG_FILE = PACKAGE_DIR / "catalog.json"
OVERRIDES_FILE = PACKAGE_DIR / "catalog_overrides.json"


def parse_range_limit(text: str) -> int | None:
    """Longest date range Garmin documents in a description ("maximum of 31 days", "of 1 year")."""
    match = _LIMIT_RE.search(text or "")
    if not match:
        return None
    count = int(match.group(1))
    return count * 366 if match.group(2).lower().startswith("year") else count


def spec_sha256(openapi: dict[str, Any]) -> str:
    canonical = json.dumps(openapi, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _range_params(names: set[str]) -> list[str] | None:
    for first, second in RANGE_PAIRS:
        if first in names and second in names:
            return [first, second]
    return None


def _documented_limit(operation: dict[str, Any]) -> int | None:
    texts = [operation.get("summary", ""), operation.get("description", "")]
    texts += [p.get("description", "") for p in operation.get("parameters", [])]
    for text in texts:
        limit = parse_range_limit(text)
        if limit:
            return limit
    return None


def build_catalog(
    openapi: dict[str, Any], overrides: dict[str, dict[str, Any]], *, generated_at: str
) -> dict[str, Any]:
    endpoints = []
    for path, item in openapi["paths"].items():
        if path in EXCLUDED_PATHS or "get" not in item:
            continue
        operation = item["get"]
        params = [
            {
                "name": p["name"],
                "location": p["in"],
                "required": bool(p.get("required", False)),
                "type": (p.get("schema") or {}).get("type", "string"),
                "description": p.get("description", ""),
            }
            for p in operation.get("parameters", [])
            if p["in"] in ("path", "query")
        ]
        override = overrides.get(path, {})
        range_params = _range_params({p["name"] for p in params})
        documented = _documented_limit(operation) if range_params else None
        endpoints.append(
            {
                "path": path,
                "summary": operation.get("summary") or operation.get("description", ""),
                "params": params,
                "sensitive": path.startswith(SENSITIVE_PREFIXES),
                "verified": bool(override.get("verified", False)),
                "max_range_days": override.get("max_range_days", documented),
                "max_page_size": override.get("max_page_size"),
                "range_params": range_params,
            }
        )
    endpoints.sort(key=lambda e: e["path"])
    return {
        "source_url": SWAGGER_PAGE,
        "spec_sha256": spec_sha256(openapi),
        "generated_at": generated_at,
        "endpoints": endpoints,
    }


def _committed_hash() -> str | None:
    if not CATALOG_FILE.exists():
        return None
    value = json.loads(CATALOG_FILE.read_text(encoding="utf-8")).get("spec_sha256")
    return str(value) if value else None


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print("Usage: python scripts/build_catalog.py build/openapi.json [--check] [--force]", file=sys.stderr)
        return 2
    openapi = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    changed = spec_sha256(openapi) != _committed_hash()
    if "--check" in argv:
        print("changed" if changed else "unchanged")
        return 0
    if not changed and "--force" not in argv:
        print("Garmin's spec is unchanged: catalog.json left as it is.")
        return 0
    overrides = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8")) if OVERRIDES_FILE.exists() else {}
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    catalog = build_catalog(openapi, overrides, generated_at=generated_at)
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(catalog['endpoints'])} endpoints written to {CATALOG_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
