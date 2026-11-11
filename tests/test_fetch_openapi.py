from pathlib import Path

import pytest
from fetch_openapi import SWAGGER_PAGE, OpenApiFetchError, extract_spec, find_bundle_url

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "swagger_page.html").read_text(encoding="utf-8")
BUNDLE = (FIXTURES / "swagger_bundle.js").read_text(encoding="utf-8")


def test_swagger_page_constant():
    assert SWAGGER_PAGE == "https://developer.garmin.com/gc-developer-program/personal/swagger-docs/"


def test_find_bundle_url():
    url = find_bundle_url(PAGE, "https://developer.garmin.com")
    assert url == (
        "https://developer.garmin.com/component---src-pages-gc-developer-program-personal-swagger-docs-js-"
        "715115a6210d45afc282.js"
    )


def test_extract_spec_unescapes():
    spec = extract_spec(BUNDLE)
    assert spec["openapi"] == "3.0.1"
    assert spec["paths"]["/a"]["get"]["summary"] == "Cafè l'ultimo"
    assert spec["paths"]["/b/{id}"]["get"]["summary"] == "B\\C"


def test_page_without_bundle_fails_loudly():
    with pytest.raises(OpenApiFetchError, match="no swagger-docs bundle"):
        find_bundle_url("<html></html>", "https://developer.garmin.com")


def test_bundle_without_spec_fails_loudly():
    with pytest.raises(OpenApiFetchError, match="no embedded OpenAPI document"):
        extract_spec("var x = 1;")


def test_spec_without_paths_fails_loudly():
    with pytest.raises(OpenApiFetchError, match=r"not an OpenAPI 3.x document with paths"):
        extract_spec("""JSON.parse('{"openapi":"3.0.1","paths":{}}')""")
