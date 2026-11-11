import pytest
from build_catalog import build_catalog

from garmin_dynamic_mcp.catalog import Catalog
from garmin_dynamic_mcp.compact import ACTIVITY_SEARCH_PATH
from garmin_dynamic_mcp.errors import GarminError
from garmin_dynamic_mcp.fetch import MAX_ACTIVITIES, MAX_REQUESTS, Fetcher

STEPS = "/usersummary-service/stats/steps/daily/{startDate}/{endDate}"
SUMMARIES = "/usersummary-service/v2/dailysummaries"
HRV = "/hrv-service/hrv/daily/{fromDate}/{toDate}"


def _p(name, location, required=False):
    return {"name": name, "in": location, "required": required, "schema": {"type": "string"}}


OPENAPI = {
    "paths": {
        STEPS: {"get": {"parameters": [_p("startDate", "path", True), _p("endDate", "path", True)]}},
        SUMMARIES: {"get": {"parameters": [_p("startDate", "query"), _p("endDate", "query")]}},
        HRV: {"get": {"parameters": [_p("fromDate", "path", True), _p("toDate", "path", True)]}},
        ACTIVITY_SEARCH_PATH: {
            "get": {
                "parameters": [
                    _p("start", "query"),
                    _p("limit", "query"),
                    _p("startDate", "query"),
                    _p("endDate", "query"),
                ]
            }
        },
    }
}


class FakeClient:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    async def get_json(self, url_path, params=None):
        self.calls.append((url_path, dict(params or {})))
        return self.responder(url_path, dict(params or {}))


def _fetcher(responder, overrides=None):
    catalog = Catalog.from_dict(build_catalog(OPENAPI, overrides or {}, generated_at="t"))
    client = FakeClient(responder)
    return Fetcher(client, catalog), client


def _search_pages(total):
    def responder(_path, params):
        start, limit = int(params.get("start", 0)), int(params["limit"])
        return [{"i": i} for i in range(start, min(start + limit, total))]

    return responder


SEARCH_OVERRIDE = {ACTIVITY_SEARCH_PATH: {"max_page_size": 200}}


async def test_activities_paginate_until_short_page():
    fetcher, client = _fetcher(_search_pages(437), SEARCH_OVERRIDE)
    result = await fetcher.fetch(ACTIVITY_SEARCH_PATH, {})
    assert len(result.data) == 437 and result.partial is False and result.notes == ()
    assert [(p["start"], p["limit"]) for _, p in client.calls] == [("0", "200"), ("200", "200"), ("400", "200")]


async def test_activities_user_limit_is_total_cap():
    fetcher, client = _fetcher(_search_pages(1000), SEARCH_OVERRIDE)
    result = await fetcher.fetch(ACTIVITY_SEARCH_PATH, {"limit": "50"})
    assert len(result.data) == 50 and result.partial is False
    assert [p["limit"] for _, p in client.calls] == ["50"]


async def test_activities_default_page_size_when_unknown():
    fetcher, client = _fetcher(_search_pages(10))
    await fetcher.fetch(ACTIVITY_SEARCH_PATH, {})
    assert client.calls[0][1]["limit"] == "100"


async def test_activities_caps_at_1000_and_marks_partial():
    fetcher, client = _fetcher(_search_pages(5000), SEARCH_OVERRIDE)
    result = await fetcher.fetch(ACTIVITY_SEARCH_PATH, {})
    assert len(result.data) == MAX_ACTIVITIES == 1000
    assert result.partial is True
    assert "1000" in result.notes[0] and "startDate" in result.notes[0]
    assert len(client.calls) == 5


async def test_range_split_into_chunks_of_max_range_days():
    fetcher, client = _fetcher(lambda path, _p: [{"url": path}], {STEPS: {"max_range_days": 31}})
    result = await fetcher.fetch(STEPS, {"startDate": "2026-01-01", "endDate": "2026-03-31"})
    assert [c[0] for c in client.calls] == [
        "/usersummary-service/stats/steps/daily/2026-01-01/2026-01-31",
        "/usersummary-service/stats/steps/daily/2026-02-01/2026-03-03",
        "/usersummary-service/stats/steps/daily/2026-03-04/2026-03-31",
    ]
    assert len(result.data) == 3 and result.partial is False


async def test_range_results_concatenate_data_wrapper_with_query_params():
    fetcher, client = _fetcher(lambda _path, p: {"data": [{"d": p["startDate"]}]}, {SUMMARIES: {"max_range_days": 31}})
    result = await fetcher.fetch(SUMMARIES, {"startDate": "2026-01-01", "endDate": "2026-02-15"})
    assert result.data == {"data": [{"d": "2026-01-01"}, {"d": "2026-02-01"}]}
    assert [p["endDate"] for _, p in client.calls] == ["2026-01-31", "2026-02-15"]


async def test_request_cap_20_marks_partial_and_names_covered_range():
    fetcher, client = _fetcher(lambda path, _p: [path], {STEPS: {"max_range_days": 7}})
    result = await fetcher.fetch(STEPS, {"startDate": "2026-01-01", "endDate": "2026-07-19"})
    assert len(client.calls) == MAX_REQUESTS == 20
    assert result.partial is True
    assert "2026-05-20" in result.notes[0]


async def test_reversed_range_raises_invalid_request_without_calling():
    fetcher, client = _fetcher(lambda *_: [], {STEPS: {"max_range_days": 31}})
    with pytest.raises(GarminError) as exc:
        await fetcher.fetch(STEPS, {"startDate": "2026-03-01", "endDate": "2026-01-01"})
    assert exc.value.kind == "invalid_request"
    assert client.calls == []


async def test_reversed_activity_date_filters_raise_without_calling():
    fetcher, client = _fetcher(lambda *_: [], SEARCH_OVERRIDE)
    with pytest.raises(GarminError) as exc:
        await fetcher.fetch(ACTIVITY_SEARCH_PATH, {"startDate": "2026-03-01", "endDate": "2026-01-01"})
    assert exc.value.kind == "invalid_request"
    assert client.calls == []


async def test_no_split_when_endpoint_has_no_limit():
    fetcher, client = _fetcher(lambda *_: [{"x": 1}])
    result = await fetcher.fetch(HRV, {"fromDate": "2025-01-01", "toDate": "2026-01-01"})
    assert len(client.calls) == 1 and result.data == [{"x": 1}]


async def test_empty_result_is_not_an_error():
    fetcher, _ = _fetcher(lambda *_: [], {STEPS: {"max_range_days": 31}})
    result = await fetcher.fetch(STEPS, {"startDate": "2026-01-01", "endDate": "2026-01-10"})
    assert result.data == [] and result.partial is False and result.notes == ()


async def test_invalid_request_is_rejected_by_catalog_before_any_call():
    fetcher, client = _fetcher(lambda *_: [])
    with pytest.raises(GarminError):
        await fetcher.fetch("/not/in/catalog", {})
    assert client.calls == []


async def test_activities_limit_above_cap_is_capped_and_marked_partial():
    fetcher, _ = _fetcher(_search_pages(5000), SEARCH_OVERRIDE)
    result = await fetcher.fetch(ACTIVITY_SEARCH_PATH, {"limit": "5000"})
    assert len(result.data) == MAX_ACTIVITIES
    assert result.partial is True
    assert "1000" in result.notes[0]


@pytest.mark.parametrize("params", [{"limit": "-5"}, {"limit": "2.5"}, {"start": "-1"}, {"limit": "1e3"}])
async def test_activity_search_rejects_bad_numbers(params):
    fetcher, client = _fetcher(_search_pages(10))
    with pytest.raises(GarminError) as exc:
        await fetcher.fetch(ACTIVITY_SEARCH_PATH, params)
    assert exc.value.kind == "invalid_request" and client.calls == []


async def test_activity_search_non_list_page_is_upstream_error():
    fetcher, _ = _fetcher(lambda _p, _q: {"error": "x"})
    with pytest.raises(GarminError) as exc:
        await fetcher.fetch(ACTIVITY_SEARCH_PATH, {"limit": "5"})
    assert exc.value.kind == "upstream"


async def test_chunk_error_keeps_previous_chunks_as_partial():
    def responder(_path, params):
        if params.get("startDate", _path.split("/")[-2]) != "2026-01-01" and "2026-01-01" not in _path:
            raise GarminError("upstream", "Garmin answered with an error (HTTP 500).")
        return [{"calendarDate": "2026-01-01", "totalSteps": 1}]

    fetcher, client = _fetcher(responder, {STEPS: {"max_range_days": 28}})
    result = await fetcher.fetch(STEPS, {"startDate": "2026-01-01", "endDate": "2026-03-01"})
    assert result.partial is True
    assert result.data == [{"calendarDate": "2026-01-01", "totalSteps": 1}]
    assert "2026-01-29" in result.notes[0] and "HTTP 500" in result.notes[0]
    assert len(client.calls) == 2


async def test_chunk_error_on_first_chunk_is_raised():
    def responder(_path, _params):
        raise GarminError("upstream", "boom")

    fetcher, _ = _fetcher(responder, {STEPS: {"max_range_days": 28}})
    with pytest.raises(GarminError):
        await fetcher.fetch(STEPS, {"startDate": "2026-01-01", "endDate": "2026-03-01"})
