import io

import pytest

from garmin_dynamic_mcp.auth import normalize_key
from garmin_dynamic_mcp.errors import GarminError
from garmin_dynamic_mcp.secret import read_secret


def _reader(chars):
    queue = list(chars)
    return lambda: queue.pop(0)


def _read(chars, clipboard=None):
    out = io.StringIO()
    value = read_secret("Key: ", out=out, getwch=_reader(chars), read_clipboard=lambda: clipboard)
    return value, out.getvalue()


def test_typed_text_is_returned_and_shown_as_stars():
    value, shown = _read("abc\r")
    assert value == "abc"
    assert shown.startswith("Key: ") and "***" in shown and "abc" not in shown


def test_pasted_characters_arrive_one_by_one_like_a_right_click_paste():
    value, _ = _read([*"GCDC_key-123", "\r"])
    assert value == "GCDC_key-123"


def test_ctrl_v_inserts_the_clipboard_and_shows_stars():
    value, shown = _read(["\x16", "\r"], clipboard="from-the-clipboard\n")
    assert value == "from-the-clipboard"
    assert "from-the-clipboard" not in shown and shown.count("*") == len("from-the-clipboard")


def test_ctrl_v_with_an_unreadable_clipboard_adds_nothing():
    value, _ = _read(["a", "\x16", "\r"], clipboard=None)
    assert value == "a"


def test_backspace_removes_the_last_character_and_erases_a_star():
    value, shown = _read(["a", "b", "\x08", "c", "\r"])
    assert value == "ac" and "\b \b" in shown


def test_ctrl_c_raises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        _read(["a", "\x03"])


def test_special_key_prefixes_are_ignored_with_their_code():
    value, _ = _read(["a", "\xe0", "H", "b", "\x00", "K", "\r"])
    assert value == "ab"


def test_enter_alone_returns_an_empty_string():
    assert _read(["\r"])[0] == ""


def test_normalize_key_drops_control_characters_left_by_a_paste():
    assert normalize_key("\x16GCDC_key-123\x16") == "GCDC_key-123"


def test_normalize_key_still_rejects_inner_spaces_after_dropping_controls():
    with pytest.raises(GarminError):
        normalize_key("abc\x16 def")
