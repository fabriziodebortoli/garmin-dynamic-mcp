"""Build the Claude Desktop extension (MCPB, `uv` runtime) for a released version.

The bundle only contains a manifest, a tiny entry point and a pyproject.toml that pins
`garmin-dynamic-mcp==VERSION` from PyPI, so the release must already be on PyPI when the bundle is used.

Usage: python scripts/build_mcpb.py 0.2.0      # writes build/garmin-dynamic-mcp.mcpb (needs Node/npx)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "mcpb"
STAGING = ROOT / "build" / "mcpb-staging"
OUTPUT = ROOT / "build" / "garmin-dynamic-mcp.mcpb"
MCPB_CLI = "@anthropic-ai/mcpb@2.1.2"


def stage_bundle(source: Path, dest: Path, version: str) -> None:
    """Copy the bundle sources to `dest` and write the version into manifest.json and pyproject.toml."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    manifest_file = dest / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pyproject = dest / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    text = re.sub(r'^version = "[^"]*"$', f'version = "{version}"', text, count=1, flags=re.MULTILINE)
    text = text.replace('"garmin-dynamic-mcp==0.0.0"', f'"garmin-dynamic-mcp=={version}"')
    pyproject.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        print("Usage: python scripts/build_mcpb.py X.Y.Z", file=sys.stderr)
        return 2
    npx = shutil.which("npx")
    if npx is None:
        print("npx not found: install Node.js to build the extension.", file=sys.stderr)
        return 1
    stage_bundle(SOURCE, STAGING, argv[1])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    for args in (["validate", str(STAGING / "manifest.json")], ["pack", str(STAGING), str(OUTPUT)]):
        result = subprocess.run([npx, "-y", MCPB_CLI, *args], check=False)
        if result.returncode != 0:
            return result.returncode
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
