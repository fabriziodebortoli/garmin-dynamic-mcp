import json
from pathlib import Path

import pytest
from build_catalog import SWAGGER_PAGE, build_catalog, parse_range_limit, spec_sha256

from garmin_dynamic_mcp.catalog import Catalog

CATALOG_FILE = Path(__file__).resolve().parent.parent / "src" / "garmin_dynamic_mcp" / "catalog.json"


def _op(description, *names, path_params=()):
    params = [{"name": n, "in": "query", "schema": {"type": "string"}} for n in names]
    params += [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}} for n in path_params]
    return {"get": {"summary": "s", "description": description, "parameters": params}}


@pytest.mark.parametrize(
    "text,days",
    [
        ("Get data for a date range, up to a maximum of 31 days.", 31),
        ("Maximum of 28 days.", 28),
        ("up to a maximum of 1 year.", 366),
        ("Maximum number of activities to return. Defaults to 99.", None),
        ("", None),
    ],
)
def test_parse_range_limit(text, days):
    assert parse_range_limit(text) == days


def test_limit_parsed_from_description():
    spec = {"paths": {"/x": _op("up to a maximum of 31 days.", "startDate", "endDate")}}
    built = build_catalog(spec, {}, generated_at="2026-11-10T00:00:00Z")
    assert built["endpoints"][0]["max_range_days"] == 31


def test_override_beats_parsed_limit():
    spec = {"paths": {"/x": _op("up to a maximum of 31 days.", "startDate", "endDate")}}
    built = build_catalog(spec, {"/x": {"max_range_days": 30}}, generated_at="t")
    assert built["endpoints"][0]["max_range_days"] == 30


def test_new_endpoint_is_unverified_and_sensitive_by_prefix():
    spec = {"paths": {"/nutrition-service/new/{date}": _op("", path_params=("date",))}}
    entry = build_catalog(spec, {}, generated_at="t")["endpoints"][0]
    assert entry["verified"] is False and entry["sensitive"] is True


def test_provenance_fields():
    spec = {"openapi": "3.0.1", "paths": {"/x": _op("")}}
    built = build_catalog(spec, {}, generated_at="2026-11-10T00:00:00Z")
    assert built["source_url"] == SWAGGER_PAGE
    assert built["spec_sha256"] == spec_sha256(spec)
    assert built["generated_at"] == "2026-11-10T00:00:00Z"


def test_hash_is_stable_across_key_order():
    assert spec_sha256({"a": 1, "b": {"c": 2, "d": 3}}) == spec_sha256({"b": {"d": 3, "c": 2}, "a": 1})


def test_catalog_with_provenance_still_loads():
    spec = {"paths": {"/x": _op("", "startDate", "endDate")}}
    catalog = Catalog.from_dict(build_catalog(spec, {}, generated_at="t"))
    assert "/x" in catalog.endpoints


def test_committed_catalog_matches_garmin_spec_of_2026_11_10():
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    assert data["source_url"] == SWAGGER_PAGE
    assert data["spec_sha256"] == "481dadc74076037e766f83b0a46aadf90066ea745832cc34924f4d26859833af"
    assert len(data["endpoints"]) == 25
