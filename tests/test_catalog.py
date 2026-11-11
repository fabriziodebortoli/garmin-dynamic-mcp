import pytest
from build_catalog import build_catalog

from garmin_dynamic_mcp.catalog import Catalog, load_catalog
from garmin_dynamic_mcp.errors import GarminError


def _p(name, location, required=False, type_="string"):
    return {
        "name": name,
        "in": location,
        "required": required,
        "schema": {"type": type_},
        "description": f"{name} description",
    }


def _op(summary, *params):
    return {"get": {"summary": summary, "parameters": list(params)}}


STEPS = "/usersummary-service/stats/steps/daily/{startDate}/{endDate}"
SLEEP = "/sleep-service/sleep/dailySleepSummariesByDate"
HRV = "/hrv-service/hrv/daily/{fromDate}/{toDate}"
WELLNESS_RANGE = "/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}"
DOWNLOAD = "/download-service/files/activity/{activityId}"
NUTRITION = "/nutrition-service/food/logs/{date}"
CYCLE = "/periodichealth-service/menstrualcycle/summary/{calendarDate}"
ACTIVITY = "/activity-service/activity/{activityId}"
SEARCH = "/activitylist-service/activities/search/activities"

OPENAPI = {
    "openapi": "3.0.1",
    "paths": {
        STEPS: _op("Daily steps", _p("startDate", "path", True), _p("endDate", "path", True)),
        SLEEP: _op("Sleep summaries", _p("startDate", "query"), _p("endDate", "query")),
        HRV: _op("HRV", _p("fromDate", "path", True), _p("toDate", "path", True)),
        WELLNESS_RANGE: _op("Range", _p("fromDate", "path", True), _p("untilDate", "path", True)),
        DOWNLOAD: _op("Download activity file", _p("activityId", "path", True)),
        NUTRITION: _op("Food logs", _p("date", "path", True), _p("includeGoals", "query")),
        CYCLE: _op("Cycle summary", _p("calendarDate", "path", True)),
        ACTIVITY: _op("Activity", _p("activityId", "path", True)),
        SEARCH: _op(
            "Search activities",
            _p("start", "query", type_="integer"),
            _p("limit", "query", type_="integer"),
            _p("startDate", "query"),
            _p("endDate", "query"),
        ),
    },
}


def _by_path(built):
    return {e["path"]: e for e in built["endpoints"]}


def _catalog(overrides=None, allow_sensitive=False):
    return Catalog.from_dict(build_catalog(OPENAPI, overrides or {}, generated_at="t"), allow_sensitive=allow_sensitive)


def test_build_catalog_extracts_paths_and_param_locations():
    steps = _by_path(build_catalog(OPENAPI, {}, generated_at="t"))[STEPS]
    assert steps["summary"] == "Daily steps"
    assert [(p["name"], p["location"], p["required"]) for p in steps["params"]] == [
        ("startDate", "path", True),
        ("endDate", "path", True),
    ]


def test_build_catalog_excludes_download_endpoint():
    assert DOWNLOAD not in _by_path(build_catalog(OPENAPI, {}, generated_at="t"))


def test_build_catalog_flags_sensitive():
    built = _by_path(build_catalog(OPENAPI, {}, generated_at="t"))
    assert built[NUTRITION]["sensitive"] is True
    assert built[CYCLE]["sensitive"] is True
    assert built[STEPS]["sensitive"] is False


def test_build_catalog_detects_range_params():
    built = _by_path(build_catalog(OPENAPI, {}, generated_at="t"))
    assert built[STEPS]["range_params"] == ["startDate", "endDate"]
    assert built[HRV]["range_params"] == ["fromDate", "toDate"]
    assert built[WELLNESS_RANGE]["range_params"] == ["fromDate", "untilDate"]
    assert built[SLEEP]["range_params"] == ["startDate", "endDate"]
    assert built[NUTRITION]["range_params"] is None


def test_build_catalog_applies_overrides():
    built = _by_path(
        build_catalog(
            OPENAPI, {STEPS: {"verified": True, "max_range_days": 31, "max_page_size": 200}}, generated_at="t"
        )
    )
    assert built[STEPS]["verified"] is True
    assert built[STEPS]["max_range_days"] == 31
    assert built[STEPS]["max_page_size"] == 200
    assert built[HRV]["verified"] is False
    assert built[HRV]["max_range_days"] is None


def test_validate_rejects_unknown_path():
    with pytest.raises(GarminError) as exc:
        _catalog().validate("/evil/path", {})
    assert exc.value.kind == "invalid_request"
    assert STEPS in exc.value.message


def test_validate_rejects_unknown_param_and_lists_allowed():
    with pytest.raises(GarminError) as exc:
        _catalog().validate(STEPS, {"startDate": "2026-11-01", "endDate": "2026-11-09", "foo": "1"})
    assert exc.value.kind == "invalid_request"
    assert "foo" in exc.value.message
    assert "startDate" in exc.value.message and "endDate" in exc.value.message


def test_validate_missing_required_param():
    with pytest.raises(GarminError) as exc:
        _catalog().validate(STEPS, {"startDate": "2026-11-01"})
    assert exc.value.kind == "invalid_request"
    assert "endDate" in exc.value.message


def test_validate_rejects_bad_date_format():
    with pytest.raises(GarminError) as exc:
        _catalog().validate(STEPS, {"startDate": "10/11/2026", "endDate": "2026-11-09"})
    assert exc.value.kind == "invalid_request"
    assert "YYYY-MM-DD" in exc.value.message


def test_validate_rejects_impossible_calendar_date():
    with pytest.raises(GarminError) as exc:
        _catalog().validate(STEPS, {"startDate": "2026-02-30", "endDate": "2026-03-01"})
    assert "YYYY-MM-DD" in exc.value.message


def test_validate_returns_endpoint_when_ok():
    endpoint = _catalog().validate(STEPS, {"startDate": "2026-11-01", "endDate": "2026-11-09"})
    assert endpoint.path == STEPS
    assert endpoint.range_params == ("startDate", "endDate")


def test_sensitive_disabled_by_default_and_enabled_with_flag():
    with pytest.raises(GarminError) as exc:
        _catalog().validate(NUTRITION, {"date": "2026-11-01"})
    assert exc.value.kind == "invalid_request"
    assert "GARMIN_MCP_ENABLE_SENSITIVE=1" in exc.value.message
    endpoint = _catalog(allow_sensitive=True).validate(NUTRITION, {"date": "2026-11-01"})
    assert endpoint.sensitive is True


def test_expand_substitutes_and_url_encodes_path_params_and_splits_query():
    catalog = _catalog()
    steps = catalog.endpoints[STEPS]
    assert catalog.expand(steps, {"startDate": "2026-11-01", "endDate": "2026-11-09"}) == (
        "/usersummary-service/stats/steps/daily/2026-11-01/2026-11-09",
        {},
    )
    search = catalog.endpoints[SEARCH]
    assert catalog.expand(search, {"start": "0", "limit": "5"}) == (SEARCH, {"start": "0", "limit": "5"})
    activity = catalog.endpoints[ACTIVITY]
    assert catalog.expand(activity, {"activityId": "12/3"}) == ("/activity-service/activity/12%2F3", {})


def test_real_catalog_has_25_endpoints_3_sensitive():
    catalog = load_catalog(allow_sensitive=True)
    assert len(catalog.endpoints) == 25
    assert sum(1 for e in catalog.endpoints.values() if e.sensitive) == 3
    assert SEARCH in catalog.endpoints
    assert DOWNLOAD not in catalog.endpoints


@pytest.mark.parametrize("bad", ["..", ".", "../hrv-service/hrv/2026-01-01", "12/3", "12%2F3", "1 2", ""])
def test_validate_rejects_path_param_values_that_could_escape_the_catalog(bad):
    with pytest.raises(GarminError) as exc:
        _catalog().validate(ACTIVITY, {"activityId": bad})
    assert exc.value.kind == "invalid_request"
    assert "activityId" in exc.value.message


def test_validate_accepts_plain_numeric_activity_id():
    assert _catalog().validate(ACTIVITY, {"activityId": "25016191288"}).path == ACTIVITY


@pytest.mark.parametrize("bad", ["12\n", "١٢٣", "12 "])
def test_validate_path_params_use_full_ascii_match(bad):
    with pytest.raises(GarminError) as exc:
        _catalog().validate(ACTIVITY, {"activityId": bad})
    assert exc.value.kind == "invalid_request"


def test_real_catalog_dailysummaries_limit_is_one_year():
    assert load_catalog().endpoints["/usersummary-service/v2/dailysummaries"].max_range_days == 366
