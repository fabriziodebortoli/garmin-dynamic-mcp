"""Response reduction: field selection, default activity view, truncation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

ACTIVITY_SEARCH_PATH = "/activitylist-service/activities/search/activities"

ACTIVITY_DEFAULT_FIELDS: tuple[str, ...] = (
    "activityId",
    "activityName",
    "startTimeLocal",
    "activityType.typeKey",
    "distance",
    "duration",
    "elevationGain",
    "averageSpeed",
    "averageHR",
    "maxHR",
    "averageRunningCadenceInStepsPerMinute",
    "steps",
    "calories",
    "avgPower",
    "activityTrainingLoad",
)

_HOW_TO_NARROW = "Narrow the date range or use `fields` to receive fewer fields."


def _pick(item: Any, path: str) -> Any:
    value = item
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _select_item(item: Any, fields: Sequence[str]) -> dict[str, Any]:
    return {field: _pick(item, field) for field in fields}


def select_fields(data: Any, fields: Sequence[str]) -> Any:
    """Keep only the requested fields (dotted paths), as flat keys."""
    if isinstance(data, list):
        return [_select_item(item, fields) for item in data]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return {**data, "data": [_select_item(item, fields) for item in data["data"]]}
    if isinstance(data, dict):
        return _select_item(data, fields)
    return data


def _items(data: Any) -> list[Any] | None:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return list(data["data"])
    return None


def _is_date_key(key: str) -> bool:
    return key in ("calendarDate", "date") or key.endswith("Date")


def _notes(original: Any, fields: Sequence[str] | None) -> list[str]:
    items = _items(original)
    if not items or not all(isinstance(item, dict) for item in items):
        return []
    notes = [
        f"No item has field '{field}'; check the name (fields are dotted paths, e.g. activityType.typeKey)."
        for field in fields or ()
        if all(_pick(item, field) is None for item in items)
    ]
    empty = sum(
        1
        for item in items
        if any(not _is_date_key(k) for k in item) and all(v is None for k, v in item.items() if not _is_date_key(k))
    )
    if empty:
        notes.append(f"{empty} of {len(items)} items have no data (the device recorded nothing for those days).")
    return notes


def compact(path: str, data: Any, fields: Sequence[str] | None) -> tuple[Any, list[str]]:
    """Reduce a response; return the reduced data and notes for the model."""
    notes = _notes(data, fields)
    if fields:
        return select_fields(data, fields), notes
    if path == ACTIVITY_SEARCH_PATH:
        return select_fields(data, ACTIVITY_DEFAULT_FIELDS), notes
    return data, notes


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _truncate_list(items: list[Any], budget: int) -> tuple[list[Any], str | None]:
    if _size(items) <= budget:
        return items, None
    if _size(items[0]) + 2 > budget:
        note = (
            f"Result truncated: the first item alone is {_size(items[0])} characters, "
            f"too large. Use `fields` to pick only the fields you need. {_HOW_TO_NARROW}"
        )
        return [], note
    kept: list[Any] = []
    used = 2
    for item in items:
        cost = _size(item) + 2
        if kept and used + cost > budget:
            break
        kept.append(item)
        used += cost
    note = f"Result truncated: showing {len(kept)} of {len(items)} items. {_HOW_TO_NARROW}"
    return kept, note


def truncate(data: Any, max_chars: int = 40_000) -> tuple[Any, str | None]:
    """Cut an oversized response at whole items; return the data and a note (or None)."""
    if _size(data) <= max_chars:
        return data, None
    if isinstance(data, list):
        return _truncate_list(data, max_chars)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        rest = {k: v for k, v in data.items() if k != "data"}
        kept, note = _truncate_list(data["data"], max_chars - _size(rest))
        return {**rest, "data": kept}, note
    if isinstance(data, dict):
        first_key = next(iter(data))
        if _size({first_key: data[first_key]}) > max_chars:
            note = (
                f"Result truncated: field {first_key} alone is "
                f"{_size(data[first_key])} characters, too large. "
                "Use `fields` to pick only the fields you need."
            )
            return {}, note
        kept_obj: dict[str, Any] = {}
        used = 2
        for key, value in data.items():
            cost = _size({key: value})
            if kept_obj and used + cost > max_chars:
                break
            kept_obj[key] = value
            used += cost
        dropped = [k for k in data if k not in kept_obj]
        note = f"Result truncated: omitted fields {', '.join(dropped)}. {_HOW_TO_NARROW}"
        return kept_obj, note
    return data, None
