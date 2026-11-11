"""Errors shown to the user."""

from typing import Literal

Kind = Literal[
    "key_missing",
    "key_rejected",
    "rate_limited",
    "upstream",
    "network",
    "invalid_request",
]


class GarminError(Exception):
    """An error whose message is written for the user (and never contains the key)."""

    def __init__(self, kind: Kind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
