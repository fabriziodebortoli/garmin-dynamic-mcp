import asyncio
import time

import httpx
import pytest
import respx

from garmin_dynamic_mcp.updates import PYPI_URL, UpdateChecker, parse_version


@pytest.mark.parametrize(
    "text,expected",
    [("0.3.0", (0, 3, 0)), ("1.10.2", (1, 10, 2)), ("0.3.0rc1", None), ("0.3.dev1", None), ("<html>", None)],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


async def _settle(checker):
    checker.start()
    if checker._task is not None:
        await asyncio.wait({checker._task}, timeout=5)


@respx.mock
async def test_newer_version_produces_notice():
    respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "0.3.0"}}))
    checker = UpdateChecker("0.2.0", httpx.AsyncClient(), {})
    await _settle(checker)
    notice = checker.notice
    assert notice is not None
    assert notice["current"] == "0.2.0" and notice["latest"] == "0.3.0"
    assert "uvx garmin-dynamic-mcp@latest update" in notice["how_to_update"]
    assert notice["release_notes"].endswith("/releases/tag/v0.3.0")


@respx.mock
async def test_same_or_older_version_gives_no_notice():
    respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "0.2.0"}}))
    checker = UpdateChecker("0.2.0", httpx.AsyncClient(), {})
    await _settle(checker)
    assert checker.notice is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"info": {"version": "0.3.0rc1"}}),
        httpx.Response(503, text=""),
        httpx.Response(200, json={"unexpected": True}),
    ],
)
@respx.mock
async def test_bad_or_prerelease_answers_give_no_notice(response):
    respx.get(PYPI_URL).mock(return_value=response)
    checker = UpdateChecker("0.2.0", httpx.AsyncClient(), {})
    await _settle(checker)
    assert checker.notice is None


@respx.mock
async def test_network_error_gives_no_notice():
    respx.get(PYPI_URL).mock(side_effect=httpx.ConnectError("down"))
    checker = UpdateChecker("0.2.0", httpx.AsyncClient(), {})
    await _settle(checker)
    assert checker.notice is None


@respx.mock
async def test_start_does_not_wait_for_a_slow_pypi():
    async def slow(_request):
        await asyncio.sleep(10)
        return httpx.Response(200, json={"info": {"version": "9.9.9"}})

    respx.get(PYPI_URL).mock(side_effect=slow)
    checker = UpdateChecker("0.2.0", httpx.AsyncClient(), {})
    began = time.monotonic()
    checker.start()
    assert checker.notice is None
    assert time.monotonic() - began < 0.5
    checker._task.cancel()


@respx.mock
async def test_opt_out_makes_no_request():
    route = respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "0.3.0"}}))
    checker = UpdateChecker("0.2.0", httpx.AsyncClient(), {"GARMIN_MCP_NO_UPDATE_CHECK": "1"})
    await _settle(checker)
    assert not route.called and checker.notice is None


@respx.mock
async def test_check_runs_once_per_process():
    route = respx.get(PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "0.3.0"}}))
    checker = UpdateChecker("0.2.0", httpx.AsyncClient(), {})
    await _settle(checker)
    await _settle(checker)
    assert route.call_count == 1
