import httpx
import pytest
import respx
from conftest import make_jwt

from garmin_dynamic_mcp.auth import TOKEN_URL, TokenManager, normalize_key
from garmin_dynamic_mcp.errors import GarminError

KEY = "GCDC_secret-key-value"
IAT = 1_000_000
DAY = 86_400


def test_normalize_key_strips_whitespace_and_quotes():
    assert normalize_key('  "GCDC_x" \n') == "GCDC_x"
    assert normalize_key("'GCDC_x'") == "GCDC_x"


@pytest.mark.parametrize("raw", [None, "", "   ", '""'])
def test_normalize_key_missing_raises_key_missing(raw):
    with pytest.raises(GarminError) as exc:
        normalize_key(raw)
    assert exc.value.kind == "key_missing"
    assert "garmin-dynamic-mcp setup" in exc.value.message


def _manager(clock=lambda: IAT):
    return TokenManager(KEY, httpx.AsyncClient(), clock=clock)


@respx.mock
async def test_exchange_posts_apikey_header_and_uses_body_as_token():
    jwt = make_jwt(IAT, IAT + DAY)
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=jwt))
    assert await _manager().token() == jwt
    assert route.calls.last.request.headers["Authorization"] == f"ApiKey {KEY}"


@respx.mock
async def test_token_is_cached_and_refreshed_60s_before_expiry():
    now = [IAT]
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=make_jwt(IAT, IAT + DAY)))
    manager = _manager(clock=lambda: now[0])
    await manager.token()
    await manager.token()
    assert route.call_count == 1
    now[0] = IAT + DAY - 30
    await manager.token()
    assert route.call_count == 2


@respx.mock
async def test_invalidate_forces_new_exchange():
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=make_jwt(IAT, IAT + DAY)))
    manager = _manager()
    await manager.token()
    manager.invalidate()
    await manager.token()
    assert route.call_count == 2


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_exchange_rejection_maps_to_key_rejected(status):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(status, json={"error": "x"}))
    with pytest.raises(GarminError) as exc:
        await _manager().token()
    assert exc.value.kind == "key_rejected"
    assert "expired or was revoked" in exc.value.message


@respx.mock
async def test_short_lifetime_sets_expiry_warning():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=make_jwt(IAT, IAT + 3600)))
    manager = _manager()
    assert manager.key_expiry_warning is None
    await manager.token()
    assert "expires" in manager.key_expiry_warning


@respx.mock
async def test_full_day_lifetime_has_no_warning():
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=make_jwt(IAT, IAT + DAY)))
    manager = _manager()
    await manager.token()
    assert manager.key_expiry_warning is None


@respx.mock
async def test_network_and_server_errors_are_mapped():
    respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(GarminError) as exc:
        await _manager().token()
    assert exc.value.kind == "network"
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(GarminError) as exc:
        await _manager().token()
    assert exc.value.kind == "upstream"


@respx.mock
async def test_key_never_appears_in_error_messages():
    messages = []
    for response in (httpx.Response(401), httpx.Response(503), httpx.ConnectError("boom")):
        if isinstance(response, Exception):
            respx.post(TOKEN_URL).mock(side_effect=response)
        else:
            respx.post(TOKEN_URL).mock(return_value=response)
        with pytest.raises(GarminError) as exc:
            await _manager().token()
        messages.append(exc.value.message)
    assert all(KEY not in m for m in messages)


def test_normalize_key_strips_bom_quotes_and_newlines():
    assert normalize_key('﻿ "abc-123"\r\n') == "abc-123"


@pytest.mark.parametrize("raw", ["abc 123", "abc\t123", "abcè123"])
def test_normalize_key_rejects_inner_whitespace_or_non_ascii_without_echoing_it(raw):
    with pytest.raises(GarminError) as exc:
        normalize_key(raw)
    assert exc.value.kind == "key_missing"
    assert "abc" not in exc.value.message


@respx.mock
async def test_token_cache_survives_a_clock_far_ahead_of_garmin():
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, text=make_jwt(IAT, IAT + DAY)))
    manager = _manager(clock=lambda: IAT + DAY + 3600)  # local clock a day and an hour ahead
    await manager.token()
    await manager.token()
    assert route.call_count == 1
    assert manager.key_expiry_warning is None


@respx.mock
async def test_a_deleted_key_answers_404_and_the_message_says_so():
    """Garmin answers 404 'Personal API Key with ID ... does not exist' for a key that was deleted or replaced."""
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(404, json={"message": "Personal API Key with ID x does not exist."})
    )
    with pytest.raises(GarminError) as exc:
        await _manager().token()
    assert exc.value.kind == "key_rejected"
    assert "does not exist" in exc.value.message and "uvx garmin-dynamic-mcp setup" in exc.value.message
    assert "ID" not in exc.value.message  # never echo what Garmin sent back
