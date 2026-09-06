"""Tests for the desktop viewer's API endpoints.

Two properties matter most here.

Coordinate mapping: the stream is downscaled (1280px by default from a
1920x1080 screen), so a click on the panel arrives in the image's
coordinate space and must be scaled back. Getting this wrong doesn't
raise - it just clicks somewhere else on the user's real desktop, which is
exactly the class of fault that reached them last time.

Gating: desktop_input is a second entry point into helpers/input_control,
which performs no permission checks of its own. If it did not enforce the
same three gates as the agent-facing tool, a disabled or kill-switched
config would still be drivable from the browser.
"""

from __future__ import annotations

import pytest

from plugins._win_desktop.api import desktop_input as di
from plugins._win_desktop.api import desktop_stream as ds


def _handler():
    return di.DesktopInput(app=None, thread_lock=None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_real_input(monkeypatch):
    """Nothing here may reach the OS or the real audit log."""
    performed: list[tuple] = []
    for name in ("move", "click", "scroll", "type_text", "press_keys"):
        monkeypatch.setattr(
            di.input_control,
            name,
            lambda *a, _n=name, **k: performed.append((_n, a, k)),
        )
    monkeypatch.setattr(di.input_control, "get_screen_size", lambda: (1920, 1080))

    async def fake_append(record):
        return record

    monkeypatch.setattr(di.audit_log, "append_record", fake_append)
    return performed


def _allow(monkeypatch, control_enabled=True, tripped=False):
    monkeypatch.setattr(
        di.capture,
        "get_config",
        lambda agent=None: {
            "capture_enabled": True,
            "capture_max_edge": 1280,
            "capture_jpeg_quality": 60,
            "control_enabled": control_enabled,
        },
    )
    monkeypatch.setattr(di.kill_switch, "is_tripped", lambda: tripped)
    monkeypatch.setattr(di.kill_switch, "denial_message", lambda: "KILL SWITCH ACTIVE")


# ------------------------------------------------------------------
# Coordinate mapping
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_is_scaled_from_frame_space_to_screen_space(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    # Centre of a 1280x720 rendering of a 1920x1080 screen.
    await _handler().process(
        {"action": "click", "x": 640, "y": 360, "frame_width": 1280, "frame_height": 720},
        None,  # type: ignore[arg-type]
    )
    assert _no_real_input[0][1] == (960, 540)


@pytest.mark.asyncio
async def test_mapping_handles_a_letterboxed_render(monkeypatch, _no_real_input):
    """The panel reports the <img>'s own box, which need not match the
    stream's aspect ratio exactly."""
    _allow(monkeypatch)
    await _handler().process(
        {"action": "click", "x": 100, "y": 50, "frame_width": 400, "frame_height": 200},
        None,  # type: ignore[arg-type]
    )
    assert _no_real_input[0][1] == (480, 270)


@pytest.mark.asyncio
async def test_missing_frame_size_is_treated_as_screen_space(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    await _handler().process(
        {"action": "click", "x": 12, "y": 34}, None  # type: ignore[arg-type]
    )
    assert _no_real_input[0][1] == (12, 34)


@pytest.mark.asyncio
async def test_zero_frame_size_does_not_divide_by_zero(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    result = await _handler().process(
        {"action": "click", "x": 5, "y": 5, "frame_width": 0, "frame_height": 0},
        None,  # type: ignore[arg-type]
    )
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_non_numeric_coordinates_are_reported(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    result = await _handler().process(
        {"action": "click", "x": "middle", "y": 5}, None  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert _no_real_input == []


# ------------------------------------------------------------------
# Gating - enforced here, not inherited
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_control_blocks_browser_input(monkeypatch, _no_real_input):
    _allow(monkeypatch, control_enabled=False)
    for payload in (
        {"action": "click", "x": 1, "y": 1},
        {"action": "type", "text": "x"},
        {"action": "key", "keys": "enter"},
    ):
        result = await _handler().process(payload, None)  # type: ignore[arg-type]
        assert result["ok"] is False
    assert _no_real_input == []


@pytest.mark.asyncio
async def test_kill_switch_blocks_browser_input(monkeypatch, _no_real_input):
    _allow(monkeypatch, tripped=True)
    result = await _handler().process(
        {"action": "click", "x": 1, "y": 1}, None  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert "KILL SWITCH ACTIVE" in result["error"]
    assert _no_real_input == []


@pytest.mark.asyncio
async def test_unknown_action_is_rejected(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    result = await _handler().process(
        {"action": "wipe_disk"}, None  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert _no_real_input == []


@pytest.mark.asyncio
async def test_each_action_dispatches(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    cases = [
        ({"action": "move", "x": 1, "y": 1}, "move"),
        ({"action": "click", "x": 1, "y": 1}, "click"),
        ({"action": "scroll", "x": 1, "y": 1, "amount": -1}, "scroll"),
        ({"action": "type", "text": "hi"}, "type_text"),
        ({"action": "key", "keys": "ctrl+s"}, "press_keys"),
    ]
    for payload, expected in cases:
        _no_real_input.clear()
        await _handler().process(payload, None)  # type: ignore[arg-type]
        assert _no_real_input and _no_real_input[0][0] == expected


# ------------------------------------------------------------------
# Stream endpoint contract
# ------------------------------------------------------------------

def test_stream_is_a_get_endpoint():
    """An <img src> can only issue a GET."""
    assert ds.DesktopStream.get_methods() == ["GET"]


def test_stream_requires_auth_but_not_csrf():
    """A CSRF token cannot be attached to an <img src>; the endpoint is
    read-only, and every state-changing action lives in desktop_input,
    which does require CSRF."""
    assert ds.DesktopStream.requires_auth() is True
    assert ds.DesktopStream.requires_csrf() is False


def test_input_endpoint_requires_auth_and_csrf():
    assert di.DesktopInput.requires_auth() is True
    assert di.DesktopInput.requires_csrf() is True


def test_stream_is_bounded_so_an_abandoned_tab_frees_its_worker():
    assert 0 < ds.STREAM_SECONDS <= 900
    assert 0 < ds.MAX_FPS <= 30


# ------------------------------------------------------------------
# Per-monitor viewing
# ------------------------------------------------------------------
#
# A 5760x1080 three-screen desktop scaled into a panel leaves each screen
# too small to read, so the viewer can crop to one. That adds a second
# transform to every click: scale from the rendered frame, then offset by
# the monitor's position. Missing the offset does not raise - it silently
# puts every click on the leftmost screen.

def _three_monitors(monkeypatch):
    monitors = [
        {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": False},
        {"index": 1, "x": 1920, "y": 0, "width": 1920, "height": 1080, "primary": True},
        {"index": 2, "x": 3840, "y": 0, "width": 1920, "height": 1080, "primary": False},
    ]
    monkeypatch.setattr(di.input_control, "list_monitors", lambda: monitors)
    return monitors


@pytest.mark.asyncio
async def test_click_on_a_cropped_monitor_gets_its_offset(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    _three_monitors(monkeypatch)
    # Centre of the rightmost screen, rendered at 960x540.
    await _handler().process(
        {"action": "click", "x": 480, "y": 270,
         "frame_width": 960, "frame_height": 540, "monitor": 2},
        None,  # type: ignore[arg-type]
    )
    # 480/960 of 1920 = 960, plus that monitor's x offset of 3840.
    assert _no_real_input[0][1] == (4800, 540)


@pytest.mark.asyncio
async def test_same_frame_point_differs_per_monitor(monkeypatch, _no_real_input):
    """The identical click must land on a different screen depending on
    which one is being viewed - the whole point of the offset."""
    _allow(monkeypatch)
    _three_monitors(monkeypatch)
    seen = []
    for index in (0, 1, 2):
        _no_real_input.clear()
        await _handler().process(
            {"action": "click", "x": 100, "y": 100,
             "frame_width": 1920, "frame_height": 1080, "monitor": index},
            None,  # type: ignore[arg-type]
        )
        seen.append(_no_real_input[0][1])
    assert seen == [(100, 100), (2020, 100), (3940, 100)]


@pytest.mark.asyncio
async def test_all_screens_applies_no_offset(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    _three_monitors(monkeypatch)
    # The shared fixture stubs a single-screen desktop; "all screens" scales
    # against the whole virtual desktop, so widen it for this case.
    monkeypatch.setattr(di.input_control, "get_screen_size", lambda: (5760, 1080))
    for value in ("all", None, ""):
        _no_real_input.clear()
        payload = {"action": "click", "x": 2880, "y": 540,
                   "frame_width": 5760, "frame_height": 1080}
        if value is not None:
            payload["monitor"] = value
        await _handler().process(payload, None)  # type: ignore[arg-type]
        assert _no_real_input[0][1] == (2880, 540)


@pytest.mark.asyncio
async def test_unknown_monitor_is_rejected(monkeypatch, _no_real_input):
    _allow(monkeypatch)
    _three_monitors(monkeypatch)
    result = await _handler().process(
        {"action": "click", "x": 1, "y": 1, "monitor": 9}, None  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert _no_real_input == []
