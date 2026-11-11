"""Download Garmin's Personal API OpenAPI specification from the Swagger page.

The Swagger page is a JavaScript app: the specification is embedded in one of its bundles as
JSON.parse('{"openapi":...}'). This script finds that bundle, extracts and parses the document.

Usage: python scripts/fetch_openapi.py [build/openapi.json]
Exit code 1 with a one-line reason if Garmin changed the page and the spec can't be found.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

SWAGGER_PAGE = "https://developer.garmin.com/gc-developer-program/personal/swagger-docs/"
_SCRIPT_RE = re.compile(r'<script[^>]*\ssrc="([^"]*swagger-docs[^"]*\.js)"')
_MARKER = "JSON.parse('"
_ESCAPE_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.DOTALL)
_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


class OpenApiFetchError(Exception):
    """The specification could not be found where it used to be."""


def find_bundle_url(html: str, base: str) -> str:
    match = _SCRIPT_RE.search(html)
    if not match:
        raise OpenApiFetchError("swagger page has no swagger-docs bundle")
    return urljoin(base, match.group(1))


def _js_unescape(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        code = match.group(1)
        if code[0] in "ux" and len(code) > 1:
            return chr(int(code[1:], 16))
        return _SIMPLE.get(code, code)

    return _ESCAPE_RE.sub(replace, raw)


def _js_string_end(text: str, start: int) -> int:
    """Index of the closing single quote of a JS string literal starting at `start`."""
    i = start
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "'":
            return i
        i += 1
    raise OpenApiFetchError("bundle has no embedded OpenAPI document (unterminated string)")


def extract_spec(bundle_js: str) -> dict[str, Any]:
    position = 0
    while True:
        index = bundle_js.find(_MARKER, position)
        if index < 0:
            raise OpenApiFetchError("bundle has no embedded OpenAPI document")
        start = index + len(_MARKER)
        end = _js_string_end(bundle_js, start)
        position = end
        if not bundle_js.startswith('{"openapi"', start):
            continue
        try:
            spec = json.loads(_js_unescape(bundle_js[start:end]))
        except ValueError as err:
            raise OpenApiFetchError(f"embedded OpenAPI document is not valid JSON ({err})") from err
        if not str(spec.get("openapi", "")).startswith("3.") or not spec.get("paths"):
            raise OpenApiFetchError("not an OpenAPI 3.x document with paths")
        return dict(spec)


def fetch_spec(http: httpx.Client) -> tuple[dict[str, Any], str]:
    page = http.get(SWAGGER_PAGE)
    page.raise_for_status()
    bundle_url = find_bundle_url(page.text, SWAGGER_PAGE)
    bundle = http.get(bundle_url)
    bundle.raise_for_status()
    return extract_spec(bundle.text), bundle_url


def main(argv: list[str]) -> int:
    target = Path(argv[1] if len(argv) > 1 else "build/openapi.json")
    try:
        with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "garmin-dynamic-mcp-ci"}) as http:
            spec, bundle_url = fetch_spec(http)
    except (OpenApiFetchError, httpx.HTTPError) as err:
        print(f"fetch_openapi: {err}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(spec['paths'])} paths from {bundle_url} written to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
