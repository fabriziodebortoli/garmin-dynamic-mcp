import json

from garmin_dynamic_mcp.compact import (
    ACTIVITY_DEFAULT_FIELDS,
    ACTIVITY_SEARCH_PATH,
    compact,
    select_fields,
    truncate,
)

ACTIVITY = {
    "activityId": 1,
    "activityName": "Corsa",
    "startTimeLocal": "2026-11-09 07:43:03",
    "activityType": {"typeKey": "running", "typeId": 1},
    "distance": 3785.1,
    "duration": 1410.7,
    "averageRunningCadenceInStepsPerMinute": 167.8,
    "ownerProfileImageUrlSmall": "https://example.invalid/img.png",
    "splitSummaries": [{"noOfSplits": 1}],
}


def test_select_fields_returns_flat_dotted_keys():
    result = select_fields([ACTIVITY], ["startTimeLocal", "activityType.typeKey"])
    assert result == [{"startTimeLocal": "2026-11-09 07:43:03", "activityType.typeKey": "running"}]


def test_select_fields_applies_inside_data_wrapper():
    result = select_fields({"data": [ACTIVITY]}, ["distance"])
    assert result == {"data": [{"distance": 3785.1}]}


def test_select_fields_applies_to_a_single_object():
    assert select_fields(ACTIVITY, ["activityId"]) == {"activityId": 1}


def test_select_fields_missing_or_null_path_gives_none():
    result = select_fields([{"a": None}, {}, {"b": 5}], ["a", "b.c"])
    assert result == [
        {"a": None, "b.c": None},
        {"a": None, "b.c": None},
        {"a": None, "b.c": None},
    ]


def test_default_view_for_activity_search_when_fields_none():
    result, _ = compact(ACTIVITY_SEARCH_PATH, [ACTIVITY], None)
    assert list(result[0]) == list(ACTIVITY_DEFAULT_FIELDS)
    assert "ownerProfileImageUrlSmall" not in result[0]
    assert result[0]["activityType.typeKey"] == "running"
    assert result[0]["averageRunningCadenceInStepsPerMinute"] == 167.8
    assert result[0]["avgPower"] is None


def test_explicit_fields_override_default_view():
    assert compact(ACTIVITY_SEARCH_PATH, [ACTIVITY], ["distance"])[0] == [{"distance": 3785.1}]


def test_other_endpoints_untouched_when_fields_none():
    data = [{"calendarDate": "2026-11-01", "totalSteps": 1}]
    assert compact("/usersummary-service/stats/steps/daily/{startDate}/{endDate}", data, None)[0] == data


def test_truncate_noop_when_small():
    data = [{"a": 1}]
    assert truncate(data, max_chars=1000) == (data, None)


def test_truncate_keeps_whole_items_and_adds_note():
    data = [{"i": i, "pad": "x" * 1000} for i in range(100)]
    kept, note = truncate(data, max_chars=10_000)
    assert 0 < len(kept) < 100
    assert kept == data[: len(kept)]
    assert len(json.dumps(kept)) <= 10_000
    assert "truncated" in note and str(len(kept)) in note and "100" in note


def test_truncate_applies_to_data_wrapper():
    data = {"data": [{"pad": "x" * 1000} for _ in range(50)]}
    kept, note = truncate(data, max_chars=5_000)
    assert len(kept["data"]) < 50
    assert "truncated" in note


def test_truncate_large_object_drops_trailing_keys_and_names_them():
    data = {"small": 1, "big1": "x" * 5000, "big2": "y" * 5000}
    kept, note = truncate(data, max_chars=6_000)
    assert "small" in kept and "big2" not in kept
    assert "big2" in note


def test_truncate_empty_list_has_no_note():
    assert truncate([], max_chars=10) == ([], None)


def test_truncate_oversized_first_item_returns_empty_list_with_note():
    kept, note = truncate([{"pad": "x" * 5000}, {"pad": "y"}], max_chars=1000)
    assert kept == []
    assert "truncated" in note and "fields" in note and "5" in note


def test_truncate_oversized_first_key_returns_empty_object_with_note():
    kept, note = truncate({"big": "x" * 5000, "small": 1}, max_chars=1000)
    assert kept == {}
    assert "truncated" in note and "big" in note and "fields" in note


def test_truncate_default_limit_is_40000_chars_with_compact_json():
    data = [{"i": i, "pad": "x" * 1000} for i in range(100)]
    kept, _ = truncate(data)
    size = len(json.dumps(kept, separators=(",", ":")))
    assert 30_000 < size <= 40_000


def test_compact_returns_data_and_notes():
    data, notes = compact(ACTIVITY_SEARCH_PATH, [ACTIVITY], ["distance"])
    assert data == [{"distance": 3785.1}] and notes == []


def test_fields_null_in_every_item_adds_unknown_field_note():
    _, notes = compact(ACTIVITY_SEARCH_PATH, [{"a": 1}, {"a": 2}], ["a", "distnace"])
    assert any("'distnace'" in n for n in notes)
    assert not any("'a'" in n for n in notes)


def test_items_without_data_add_no_data_note():
    data = [
        {"calendarDate": "2026-11-01", "sleepTimeSeconds": None, "deepSleepSeconds": None},
        {"calendarDate": "2026-11-02", "sleepTimeSeconds": 25000, "deepSleepSeconds": 4000},
    ]
    _, notes = compact("/sleep-service/sleep/dailySleepSummariesByDate", data, None)
    assert any("1 of 2 items have no data" in n for n in notes)


def test_no_notes_for_empty_list():
    assert compact("/x", [], ["a"]) == ([], [])
