"""Catalog of allowed endpoints, generated from Garmin's Swagger specification."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any, Literal
from urllib.parse import quote

from .errors import GarminError

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_INTEGER_RE = re.compile(r"\d+", re.ASCII)
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)
_SENSITIVE_HINT = (
    "This endpoint returns sensitive health data and is disabled. "
    "To enable it, set the environment variable GARMIN_MCP_ENABLE_SENSITIVE=1."
)


@dataclass(frozen=True)
class Param:
    name: str
    location: Literal["path", "query"]
    required: bool
    type: str
    description: str


@dataclass(frozen=True)
class Endpoint:
    path: str
    summary: str
    params: tuple[Param, ...]
    sensitive: bool
    verified: bool
    max_range_days: int | None
    max_page_size: int | None
    range_params: tuple[str, str] | None


def _is_date_param(name: str) -> bool:
    return "date" in name.lower()


def _valid_date(value: str) -> bool:
    if not _DATE_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


class Catalog:
    def __init__(self, endpoints: dict[str, Endpoint], allow_sensitive: bool = False) -> None:
        self.endpoints = endpoints
        self.allow_sensitive = allow_sensitive

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], allow_sensitive: bool = False) -> Catalog:
        endpoints: dict[str, Endpoint] = {}
        for raw in data["endpoints"]:
            params = tuple(
                Param(
                    name=p["name"],
                    location=p["location"],
                    required=bool(p["required"]),
                    type=p.get("type", "string"),
                    description=p.get("description", ""),
                )
                for p in raw["params"]
            )
            range_params = raw.get("range_params")
            endpoints[raw["path"]] = Endpoint(
                path=raw["path"],
                summary=raw.get("summary", ""),
                params=params,
                sensitive=bool(raw["sensitive"]),
                verified=bool(raw["verified"]),
                max_range_days=raw.get("max_range_days"),
                max_page_size=raw.get("max_page_size"),
                range_params=(range_params[0], range_params[1]) if range_params else None,
            )
        return cls(endpoints, allow_sensitive)

    def validate(self, path: str, params: Mapping[str, str]) -> Endpoint:
        endpoint = self.endpoints.get(path)
        if endpoint is None:
            allowed = "\n".join(sorted(self.endpoints))
            raise GarminError("invalid_request", f"Unknown path: {path}. Available paths:\n{allowed}")
        if endpoint.sensitive and not self.allow_sensitive:
            raise GarminError("invalid_request", f"{path}: {_SENSITIVE_HINT}")
        known = {p.name for p in endpoint.params}
        unknown = sorted(set(params) - known)
        if unknown:
            raise GarminError(
                "invalid_request",
                f"Unknown parameters for {path}: {', '.join(unknown)}. "
                f"Allowed parameters: {', '.join(sorted(known)) or 'none'}.",
            )
        missing = [p.name for p in endpoint.params if p.required and p.name not in params]
        if missing:
            raise GarminError(
                "invalid_request",
                f"Missing required parameters for {path}: {', '.join(missing)}.",
            )
        for name, value in params.items():
            if _is_date_param(name) and not _valid_date(str(value)):
                raise GarminError(
                    "invalid_request",
                    f"Parameter {name} must be a valid date in the format YYYY-MM-DD (got: {value}).",
                )
        for p in endpoint.params:
            if p.location == "path" and p.name in params:
                pattern = _INTEGER_RE if p.type in ("integer", "number") else _IDENTIFIER_RE
                if not pattern.fullmatch(str(params[p.name])):
                    allowed_chars = "digits" if pattern is _INTEGER_RE else "letters, digits, - and _"
                    raise GarminError(
                        "invalid_request",
                        f"Invalid value for parameter {p.name}: only {allowed_chars} are allowed "
                        f"(got: {params[p.name]!r}).",
                    )
        return endpoint

    def expand(self, endpoint: Endpoint, params: Mapping[str, str]) -> tuple[str, dict[str, str]]:
        path = endpoint.path
        query: dict[str, str] = {}
        path_names = {p.name for p in endpoint.params if p.location == "path"}
        for name, value in params.items():
            if name in path_names:
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            else:
                query[name] = str(value)
        return path, query


def load_catalog(allow_sensitive: bool = False) -> Catalog:
    text = resources.files("garmin_dynamic_mcp").joinpath("catalog.json").read_text(encoding="utf-8")
    return Catalog.from_dict(json.loads(text), allow_sensitive=allow_sensitive)
