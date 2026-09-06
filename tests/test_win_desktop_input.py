"""Tests for plugins/_win_desktop/helpers/input_control.py.

Every test stubs `_send`, the single point where events reach the OS, so
running the suite never moves the real pointer or types into whatever
window happens to be focused.

The properties worth pinning down are the ones that would be silently
wrong rather than loudly broken: absolute-coordinate conversion (an
off-by-one at the screen edge is invisible until a click misses), the
key-up ordering for modifier combinations, and out-of-range rejection.
"""

from __future__ import annotations

import pytest

from plugins._win_desktop.helpers import input_control as ic


@pytest.fixture
def sent(monkeypatch):
    """Capture events instead of delivering them, with a fixed screen size."""
    captured: list = []
    monkeypatch.setattr(ic, "_send", lambda *events: captured.extend(events))
    monkeypatch.setattr(ic, "get_screen_size", lambda: (1920, 1080))
    return captured


# ------------------------------------------------------------------
# Absolute coordinate conversion
# ------------------------------------------------------------------

def test_origin_maps_to_zero(monkeypatch):
    monkeypatch.setattr(ic, "get_screen_size", lambda: (1920, 1080))
    assert ic._to_absolute(0, 0) == (0, 0)


def test_bottom_right_pixel_maps_to_full_range(monkeypatch):
    """The last addressable pixel must reach 65535; rounding short of it
    leaves the true screen edge unclickable."""
    monkeypatch.setattr(ic, "get_screen_size", lambda: (1920, 1080))
    assert ic._to_absolute(1919, 1079) == (65535, 65535)


def test_centre_maps_to_about_half(monkeypatch):
    monkeypatch.setattr(ic, "get_screen_size", lambda: (1920, 1080))
    ax, ay = ic._to_absolute(960, 540)
    assert abs(ax - 32768) < 40 and abs(ay - 32768) < 40


@pytest.mark.parametrize("x,y", [(-1, 10), (10, -1), (1920, 10), (10, 1080), (5000, 5000)])
def test_out_of_range_coordinates_are_rejected(monkeypatch, x, y):
    monkeypatch.setattr(ic, "get_screen_size", lambda: (1920, 1080))
    with pytest.raises(ic.InputError):
        ic._to_absolute(x, y)


# ------------------------------------------------------------------
# Mouse
# ------------------------------------------------------------------

def test_move_emits_a_single_absolute_move(sent):
    ic.move(100, 200)
    assert len(sent) == 1
    assert sent[0].union.mi.dwFlags == ic.MOUSEEVENTF_MOVE | ic.MOUSEEVENTF_ABSOLUTE


def test_click_moves_then_presses_and_releases(sent):
    ic.click(100, 200)
    # move, then down+up
    assert len(sent) == 3
    assert sent[1].union.mi.dwFlags == ic.MOUSEEVENTF_LEFTDOWN
    assert sent[2].union.mi.dwFlags == ic.MOUSEEVENTF_LEFTUP


def test_double_click_emits_two_press_release_pairs(sent):
    ic.click(10, 10, clicks=2)
    downs = [e for e in sent if e.union.mi.dwFlags == ic.MOUSEEVENTF_LEFTDOWN]
    ups = [e for e in sent if e.union.mi.dwFlags == ic.MOUSEEVENTF_LEFTUP]
    assert len(downs) == 2 and len(ups) == 2


def test_right_and_middle_buttons_use_their_own_flags(sent):
    ic.click(10, 10, button="right")
    assert any(e.union.mi.dwFlags == ic.MOUSEEVENTF_RIGHTDOWN for e in sent)
    sent.clear()
    ic.click(10, 10, button="middle")
    assert any(e.union.mi.dwFlags == ic.MOUSEEVENTF_MIDDLEDOWN for e in sent)


def test_unknown_button_is_rejected(sent):
    with pytest.raises(ic.InputError):
        ic.click(10, 10, button="scroll-wheel-thing")


@pytest.mark.parametrize("clicks", [0, 4, -1])
def test_click_count_is_bounded(sent, clicks):
    with pytest.raises(ic.InputError):
        ic.click(10, 10, clicks=clicks)


def test_scroll_direction_and_magnitude(sent):
    ic.scroll(10, 10, 3)
    wheel = [e for e in sent if e.union.mi.dwFlags == ic.MOUSEEVENTF_WHEEL][0]
    assert wheel.union.mi.mouseData == 3 * ic.WHEEL_DELTA

    sent.clear()
    ic.scroll(10, 10, -2)
    wheel = [e for e in sent if e.union.mi.dwFlags == ic.MOUSEEVENTF_WHEEL][0]
    # Negative wheel data is delivered as an unsigned DWORD.
    assert ctypes_signed(wheel.union.mi.mouseData) == -2 * ic.WHEEL_DELTA


def ctypes_signed(value: int) -> int:
    return value - 2**32 if value >= 2**31 else value


# ------------------------------------------------------------------
# Keyboard
# ------------------------------------------------------------------

def test_typing_sends_unicode_down_up_per_character(sent):
    ic.type_text("hi")
    assert len(sent) == 4  # 2 chars x (down, up)
    assert all(e.union.ki.dwFlags & ic.KEYEVENTF_UNICODE for e in sent)
    assert [e.union.ki.wScan for e in sent] == [ord("h"), ord("h"), ord("i"), ord("i")]


def test_typing_uses_scan_codes_not_virtual_keys(sent):
    """Unicode scan codes keep output independent of keyboard layout; a
    VK-based approach types the wrong characters on a non-US layout."""
    ic.type_text("@")
    assert all(e.union.ki.wVk == 0 for e in sent)
    assert sent[0].union.ki.wScan == ord("@")


def test_typing_non_ascii(sent):
    ic.type_text("é")
    assert sent[0].union.ki.wScan == ord("é")


def test_empty_text_sends_nothing(sent):
    ic.type_text("")
    assert sent == []


def test_long_text_is_chunked_but_complete(monkeypatch):
    calls: list[int] = []

    def fake_send(*events):
        calls.append(len(events))

    monkeypatch.setattr(ic, "_send", fake_send)
    ic.type_text("x" * 300)
    assert sum(calls) == 600  # 300 chars x (down, up)
    assert len(calls) > 1  # actually chunked
    assert max(calls) <= 200


def test_hotkey_parses_modifiers_and_letters():
    assert ic.parse_hotkey("ctrl+c") == [ic.VK_CODES["ctrl"], ord("C")]
    assert ic.parse_hotkey("alt+tab") == [ic.VK_CODES["alt"], ic.VK_CODES["tab"]]
    assert ic.parse_hotkey("enter") == [ic.VK_CODES["enter"]]
    assert ic.parse_hotkey("F5") == [ic.VK_CODES["f5"]]


def test_hotkey_rejects_unknown_and_empty():
    with pytest.raises(ic.InputError):
        ic.parse_hotkey("ctrl+notakey")
    with pytest.raises(ic.InputError):
        ic.parse_hotkey("")


def test_modifiers_are_released_in_reverse_order(sent):
    """ctrl must be released last, otherwise the combination can be seen
    as a bare keypress by the receiving application."""
    ic.press_keys("ctrl+shift+s")
    downs = [e.union.ki.wVk for e in sent if not e.union.ki.dwFlags & ic.KEYEVENTF_KEYUP]
    ups = [e.union.ki.wVk for e in sent if e.union.ki.dwFlags & ic.KEYEVENTF_KEYUP]
    assert downs == [ic.VK_CODES["ctrl"], ic.VK_CODES["shift"], ord("S")]
    assert ups == list(reversed(downs))


# ------------------------------------------------------------------
# Per-character delivery
# ------------------------------------------------------------------
#
# Observed live: "Hello from Agent Zero" arrived in Notepad as "Hello "
# followed by fifteen copies of the final character - the right number of
# events, the wrong content. The events were correct in Python (the tests
# above assert their scan codes), so the corruption happened on delivery:
# the whole string was sent as one atomic SendInput block, which rich text
# controls (Windows 11 Notepad uses RichEditD2DPT) do not reliably process.

def test_each_character_is_sent_as_its_own_call(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(ic, "_send", lambda *events: calls.append(events))
    monkeypatch.setattr(ic, "TYPE_CHAR_INTERVAL", 0)

    ic.type_text("abc")

    assert len(calls) == 3, "characters must not be batched into one block"
    assert all(len(events) == 2 for events in calls), "each call is one down+up pair"


def test_per_character_calls_carry_the_right_scan_codes(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(ic, "_send", lambda *events: calls.append(events))
    monkeypatch.setattr(ic, "TYPE_CHAR_INTERVAL", 0)

    ic.type_text("hi!")

    assert [events[0].union.ki.wScan for events in calls] == [
        ord("h"), ord("i"), ord("!")
    ]
    # Down then up within each call.
    for events in calls:
        assert not events[0].union.ki.dwFlags & ic.KEYEVENTF_KEYUP
        assert events[1].union.ki.dwFlags & ic.KEYEVENTF_KEYUP


def test_no_character_is_dropped_or_duplicated_in_a_long_string(monkeypatch):
    """The failure signature was a correct event count with repeated
    content, so assert the actual sequence, not just the length."""
    calls: list[tuple] = []
    monkeypatch.setattr(ic, "_send", lambda *events: calls.append(events))
    monkeypatch.setattr(ic, "TYPE_CHAR_INTERVAL", 0)

    text = "Hello from Agent Zero"
    ic.type_text(text)

    typed = "".join(chr(events[0].union.ki.wScan) for events in calls)
    assert typed == text


def test_sendinput_signature_is_declared():
    """Undeclared argtypes marshal arguments as C int, truncating 64-bit
    pointers - a fault that appears to work until it corrupts silently."""
    user32 = ic._user32()
    assert user32.SendInput.argtypes is not None
    assert user32.SendInput.restype is not None
