import json
import logging
import time

import httpx
import respx
from conftest import make_jwt
from mcp.client import Client

from garmin_dynamic_mcp.auth import TOKEN_URL
from garmin_dynamic_mcp.client import BASE_URL
from garmin_dynamic_mcp.errors import GarminError
from garmin_dynamic_mcp.server import build_server

KEY = "GCDC_secret-key-value-123"
STEPS = "/usersummary-service/stats/steps/daily/{startDate}/{endDate}"
STEPS_URL = f"{BASE_URL}/usersummary-service/stats/steps/daily/2026-11-01/2026-11-03"
SEARCH_URL = f"{BASE_URL}/activitylist-service/activities/search/activities"
NUTRITION = "/nutrition-service/food/logs/{date}"
NUTRITION_URL = f"{BASE_URL}/nutrition-service/food/logs/2026-11-01"
DAY = 86_400


def _token(lifetime=DAY):
    now = int(time.time())
    return make_jwt(now, now + lifetime)


def _mock_token(lifetime=DAY):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=_token(lifetime)))


def _env(**extra):
    return {"GARMIN_API_KEY": KEY, "GARMIN_MCP_NO_UPDATE_CHECK": "1", **extra}


async def _call(server, tool, args=None):
    async with Client(server) as client:
        result = await client.call_tool(tool, args or {})
    return result.is_error, result.content[0].text


async def test_server_exposes_exactly_two_tools():
    async with Client(build_server(_env())) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools.tools} == {"list_endpoints", "get"}


async def test_list_endpoints_marks_disabled_sensitive_and_flags_verification():
    is_error, text = await _call(build_server(_env()), "list_endpoints")
    entries = {e["path"]: e for e in json.loads(text)["endpoints"]}
    assert not is_error
    assert entries[NUTRITION]["disabled"] is True
    assert entries[STEPS]["disabled"] is False
    assert all(isinstance(e["verified"], bool) for e in entries.values())
    assert any(p["name"] == "startDate" for p in entries[STEPS]["params"])
    _, text = await _call(build_server(_env(GARMIN_MCP_ENABLE_SENSITIVE="1")), "list_endpoints")
    assert {e["path"]: e for e in json.loads(text)["endpoints"]}[NUTRITION]["disabled"] is False


@respx.mock
async def test_get_steps_returns_compact_json():
    _mock_token()
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=[{"calendarDate": "2026-11-01", "totalSteps": 9}]))
    is_error, text = await _call(
        build_server(_env()), "get", {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}}
    )
    assert not is_error
    assert json.loads(text) == {
        "data": [{"calendarDate": "2026-11-01", "totalSteps": 9}],
        "partial": False,
        "notes": [],
        "key_warning": None,
    }


@respx.mock
async def test_get_empty_result_returns_empty_data_not_error():
    _mock_token()
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=[]))
    is_error, text = await _call(
        build_server(_env()), "get", {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}}
    )
    assert not is_error
    assert json.loads(text)["data"] == [] and json.loads(text)["partial"] is False


@respx.mock
async def test_get_activity_search_accepts_numeric_params_and_uses_default_view():
    _mock_token()
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=[{"activityId": 1, "distance": 5000.0, "ownerProfileImageUrlSmall": "x"}])
    )
    is_error, text = await _call(
        build_server(_env()),
        "get",
        {"path": "/activitylist-service/activities/search/activities", "params": {"limit": 5}},
    )
    assert not is_error
    assert route.calls.last.request.url.params["limit"] == "5"
    row = json.loads(text)["data"][0]
    assert row["distance"] == 5000.0 and "ownerProfileImageUrlSmall" not in row


async def test_get_missing_key_returns_clear_error_without_crashing():
    server = build_server({})
    is_error, text = await _call(server, "get", {"path": STEPS, "params": {}})
    assert is_error and "garmin-dynamic-mcp setup" in text
    is_error, _ = await _call(server, "list_endpoints")
    assert not is_error


async def test_get_unknown_path_error_lists_allowed_paths():
    is_error, text = await _call(build_server(_env()), "get", {"path": "/evil"})
    assert is_error and STEPS in text


@respx.mock
async def test_get_includes_key_warning_for_short_lifetime():
    _mock_token(lifetime=3600)
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=[]))
    _, text = await _call(
        build_server(_env()), "get", {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}}
    )
    assert "expires" in json.loads(text)["key_warning"]


@respx.mock
async def test_sensitive_path_blocked_unless_env_flag_set():
    _mock_token()
    respx.get(NUTRITION_URL).mock(return_value=httpx.Response(200, json=[{"meal": 1}]))
    args = {"path": NUTRITION, "params": {"date": "2026-11-01"}}
    is_error, text = await _call(build_server(_env()), "get", args)
    assert is_error and "GARMIN_MCP_ENABLE_SENSITIVE=1" in text
    is_error, text = await _call(build_server(_env(GARMIN_MCP_ENABLE_SENSITIVE="1")), "get", args)
    assert not is_error and json.loads(text)["data"] == [{"meal": 1}]


@respx.mock
async def test_get_truncates_large_responses_and_marks_partial():
    _mock_token()
    big = [{"calendarDate": f"d{i}", "pad": "x" * 1000} for i in range(200)]
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=big))
    _, text = await _call(
        build_server(_env()), "get", {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}}
    )
    payload = json.loads(text)
    assert payload["partial"] is True and len(payload["data"]) < 200
    assert any("truncated" in n for n in payload["notes"])


@respx.mock
async def test_key_never_appears_in_outputs_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    outputs = []
    _mock_token()
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=[{"totalSteps": 1}]))
    ok = {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}}
    outputs.append((await _call(build_server(_env()), "get", ok))[1])
    outputs.append((await _call(build_server(_env()), "get", {"path": "/evil"}))[1])
    outputs.append((await _call(build_server(_env()), "list_endpoints"))[1])
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401))
    outputs.append((await _call(build_server(_env()), "get", ok))[1])
    assert all(KEY not in o for o in outputs)
    assert KEY not in caplog.text


async def test_list_endpoints_includes_param_descriptions_and_page_size():
    _, text = await _call(build_server(_env()), "list_endpoints")
    entries = {e["path"]: e for e in json.loads(text)["endpoints"]}
    search = entries["/activitylist-service/activities/search/activities"]
    assert all(isinstance(p["description"], str) for p in search["params"])
    assert any(p["description"] for p in search["params"])
    assert search["max_page_size"] == 200


@respx.mock
async def test_get_output_is_compact_json():
    _mock_token()
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=[{"calendarDate": "2026-11-01", "totalSteps": 9}]))
    _, text = await _call(
        build_server(_env()), "get", {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}}
    )
    assert text == json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))


async def test_get_without_any_key_says_run_setup(tmp_path):
    def raising(_env):
        raise GarminError("key_missing", "No Garmin key found. Run: uvx garmin-dynamic-mcp setup")

    is_error, text = await _call(
        build_server({}, key_loader=raising),
        "get",
        {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}},
    )
    assert is_error and "setup" in text


async def test_list_endpoints_query_filters_case_insensitive():
    _, text = await _call(build_server(_env()), "list_endpoints", {"query": "SLEEP"})
    endpoints = json.loads(text)["endpoints"]
    assert endpoints
    assert all("sleep" in (e["path"] + e["summary"]).lower() for e in endpoints)


async def test_list_endpoints_query_without_match_explains():
    _, text = await _call(build_server(_env()), "list_endpoints", {"query": "zzz-nothing"})
    payload = json.loads(text)
    assert payload["endpoints"] == [] and "zzz-nothing" in payload["note"]


async def test_tools_are_read_only_annotated_and_titled():
    async with Client(build_server(_env())) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is True
        assert tool.title


@respx.mock
async def test_get_and_list_include_update_available_when_newer(monkeypatch):
    import asyncio

    from garmin_dynamic_mcp import server as server_module
    from garmin_dynamic_mcp.updates import PYPI_URL

    monkeypatch.setattr(server_module, "__version__", "0.2.0")
    respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "0.9.0"}}))
    _mock_token()
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=[]))
    srv = build_server({**_env(), "GARMIN_MCP_NO_UPDATE_CHECK": ""})
    async with Client(srv) as client:
        await client.call_tool("list_endpoints", {})
        await asyncio.sleep(0.05)
        listed = json.loads((await client.call_tool("list_endpoints", {})).content[0].text)
        got = json.loads(
            (
                await client.call_tool(
                    "get", {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}}
                )
            )
            .content[0]
            .text
        )
    assert listed["update_available"]["latest"] == "0.9.0"
    assert got["update_available"]["latest"] == "0.9.0"


@respx.mock
async def test_no_update_field_when_opted_out():
    _mock_token()
    respx.get(STEPS_URL).mock(return_value=httpx.Response(200, json=[]))
    _, text = await _call(
        build_server({**_env(), "GARMIN_MCP_NO_UPDATE_CHECK": "1"}),
        "get",
        {"path": STEPS, "params": {"startDate": "2026-11-01", "endDate": "2026-11-03"}},
    )
    assert "update_available" not in json.loads(text)


async def test_server_reports_its_version_and_title():
    from garmin_dynamic_mcp.version import __version__

    async with Client(build_server(_env())) as client:
        info = client.server_info
    assert info.name == "garmin" and info.version == __version__ and info.title == "Garmin Dynamic MCP"
