from datetime import date

from live_probe import main, minimal_params

from garmin_dynamic_mcp.catalog import Endpoint, Param

TODAY = date(2026, 11, 10)


def _endpoint(*params, range_params=None):
    return Endpoint(
        path="/x",
        summary="",
        params=tuple(params),
        sensitive=False,
        verified=False,
        max_range_days=None,
        max_page_size=None,
        range_params=range_params,
    )


def test_minimal_params_range_endpoint_uses_last_7_days():
    ep = _endpoint(
        Param("startDate", "path", True, "string", ""),
        Param("endDate", "path", True, "string", ""),
        range_params=("startDate", "endDate"),
    )
    assert minimal_params(ep, TODAY, None) == {"startDate": "2026-11-03", "endDate": "2026-11-09"}


def test_minimal_params_single_date_param_uses_yesterday():
    ep = _endpoint(Param("calendarDate", "query", False, "string", ""))
    assert minimal_params(ep, TODAY, None) == {"calendarDate": "2026-11-09"}


def test_minimal_params_activity_endpoint_needs_an_id():
    ep = _endpoint(Param("activityId", "path", True, "string", ""))
    assert minimal_params(ep, TODAY, None) is None
    assert minimal_params(ep, TODAY, 123) == {"activityId": "123"}


def test_minimal_params_skips_optional_non_date_params_and_gives_up_on_unknown_required():
    optional = _endpoint(Param("limit", "query", False, "integer", ""))
    assert minimal_params(optional, TODAY, None) == {}
    required = _endpoint(Param("mealId", "query", True, "string", ""))
    assert minimal_params(required, TODAY, None) is None


def test_main_without_key_exits_2_and_mentions_key(capsys):
    assert main({}) == 2
    assert "garmin-dynamic-mcp setup" in capsys.readouterr().out


async def test_probe_never_calls_sensitive_endpoints():
    from build_catalog import build_catalog
    from live_probe import Probe

    from garmin_dynamic_mcp.catalog import Catalog

    nutrition = "/nutrition-service/food/logs/{date}"
    steps = "/usersummary-service/stats/steps/daily/{startDate}/{endDate}"

    def _p(name):
        return {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}

    spec = {
        "paths": {
            nutrition: {"get": {"parameters": [_p("date")]}},
            steps: {"get": {"parameters": [_p("startDate"), _p("endDate")]}},
        }
    }

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def get_json(self, url_path, params=None):
            self.calls.append(url_path)
            return []

    client = FakeClient()
    probe = Probe(client, TODAY, catalog=Catalog.from_dict(build_catalog(spec, {}, generated_at="t")), delay=0)
    await probe.probe_endpoints(None)
    assert client.calls == ["/usersummary-service/stats/steps/daily/2026-11-03/2026-11-09"]
    assert nutrition not in probe.overrides
    assert any("sensitive" in line for line in probe.lines)


def test_probe_report_is_written_outside_the_curated_docs():
    from live_probe import FINDINGS_FILE

    assert FINDINGS_FILE.parent.name == "build"
