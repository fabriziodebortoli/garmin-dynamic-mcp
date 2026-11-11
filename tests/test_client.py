import httpx
import pytest
import respx

from garmin_dynamic_mcp.client import BASE_URL, GarminClient
from garmin_dynamic_mcp.errors import GarminError

URL = f"{BASE_URL}/usersummary-service/stats/steps/daily/2026-11-01/2026-11-09"
PATH = "/usersummary-service/stats/steps/daily/2026-11-01/2026-11-09"


class FakeTokens:
    def __init__(self):
        self.issued = 0
        self.invalidated = 0

    async def token(self):
        self.issued += 1
        return f"tok{self.issued}"

    def invalidate(self):
        self.invalidated += 1


def _client(tokens=None):
    return GarminClient(tokens or FakeTokens(), httpx.AsyncClient())


@respx.mock
async def test_get_sends_bearer_and_returns_json():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=[{"calendarDate": "2026-11-01"}]))
    assert await _client().get_json(PATH) == [{"calendarDate": "2026-11-01"}]
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok1"


@respx.mock
async def test_get_passes_query_params():
    route = respx.get(f"{BASE_URL}/x").mock(return_value=httpx.Response(200, json=[]))
    await _client().get_json("/x", {"start": "0", "limit": "5"})
    assert route.calls.last.request.url.params["limit"] == "5"


@respx.mock
@pytest.mark.parametrize("bad", ["https://evil.example/x", "//evil.example/x", "relative", "http://x"])
async def test_get_refuses_absolute_urls(bad):
    route = respx.route().mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(GarminError) as exc:
        await _client().get_json(bad)
    assert exc.value.kind == "invalid_request"
    assert route.call_count == 0


@respx.mock
async def test_401_invalidates_token_and_retries_once():
    tokens = FakeTokens()
    route = respx.get(URL).mock(side_effect=[httpx.Response(401), httpx.Response(200, json=[1])])
    assert await _client(tokens).get_json(PATH) == [1]
    assert tokens.invalidated == 1
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok2"


@respx.mock
async def test_second_401_maps_to_key_rejected():
    respx.get(URL).mock(return_value=httpx.Response(401))
    with pytest.raises(GarminError) as exc:
        await _client().get_json(PATH)
    assert exc.value.kind == "key_rejected"
    assert "expired or was revoked" in exc.value.message


@respx.mock
async def test_429_maps_to_rate_limited_and_mentions_retry_after():
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(GarminError) as exc:
        await _client().get_json(PATH)
    assert exc.value.kind == "rate_limited"
    assert "120" in exc.value.message


@respx.mock
async def test_5xx_maps_to_upstream():
    respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(GarminError) as exc:
        await _client().get_json(PATH)
    assert exc.value.kind == "upstream"


@respx.mock
async def test_transport_error_maps_to_network():
    respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(GarminError) as exc:
        await _client().get_json(PATH)
    assert exc.value.kind == "network"


@respx.mock
async def test_empty_200_body_returns_none():
    respx.get(URL).mock(return_value=httpx.Response(200, content=b""))
    assert await _client().get_json(PATH) is None


@respx.mock
async def test_html_200_body_maps_to_upstream():
    respx.get(URL).mock(return_value=httpx.Response(200, text="<html>Errore</html>"))
    with pytest.raises(GarminError) as exc:
        await _client().get_json(PATH)
    assert exc.value.kind == "upstream"


@respx.mock
async def test_redirect_is_upstream_error_not_empty_body():
    respx.get(URL).mock(return_value=httpx.Response(302, headers={"Location": "https://example.invalid/"}))
    with pytest.raises(GarminError) as exc:
        await _client().get_json(PATH)
    assert exc.value.kind == "upstream" and "redirect" in exc.value.message
