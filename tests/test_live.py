import os
from datetime import date, timedelta

import httpx
import pytest

from garmin_dynamic_mcp.auth import TokenManager, normalize_key
from garmin_dynamic_mcp.catalog import load_catalog
from garmin_dynamic_mcp.client import GarminClient
from garmin_dynamic_mcp.fetch import Fetcher

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("GARMIN_API_KEY"), reason="GARMIN_API_KEY not set"),
]

STEPS = "/usersummary-service/stats/steps/daily/{startDate}/{endDate}"


async def test_live_steps_last_7_days_returns_list():
    key = normalize_key(os.environ["GARMIN_API_KEY"])
    end = date.today() - timedelta(days=1)
    async with httpx.AsyncClient(timeout=60) as http:
        fetcher = Fetcher(GarminClient(TokenManager(key, http), http), load_catalog())
        result = await fetcher.fetch(
            STEPS, {"startDate": (end - timedelta(days=6)).isoformat(), "endDate": end.isoformat()}
        )
    assert isinstance(result.data, list) and result.partial is False
