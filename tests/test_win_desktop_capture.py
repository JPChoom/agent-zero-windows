"""Tests for plugins/_win_desktop/helpers/capture.py.

The desktop capture path feeds two consumers with different needs: the
agent-facing screenshot tool (which must report native screen coordinates,
because desktop_control acts in screen space) and the MJPEG viewer (which
must be able to map a click on a downscaled frame back to the real screen).
Both depend on CapturedFrame reporting the pre-scale size alongside the
encoded size, which is what these tests pin down.

PIL's ImageGrab needs a real desktop, so the grab itself is stubbed - these
cover the scaling/encoding/config logic, not Windows' screen capture.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from plugins._win_desktop.helpers import capture


def _fake_grab(size=(1920, 1080), mode="RGB"):
    # _grab takes all_screens now, so the stub must accept it.
    def _grab(all_screens: bool = True):
        return Image.new(mode, size, color=(10, 20, 30))

    return _grab


def test_downscales_landscape_to_max_edge(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((1920, 1080)))
    frame = capture.capture_frame(max_edge=1280)
    assert (frame.width, frame.height) == (1280, 720)
    # Native size is preserved for coordinate mapping.
    assert (frame.screen_width, frame.screen_height) == (1920, 1080)


def test_downscales_portrait_by_its_longest_edge(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((1080, 1920)))
    frame = capture.capture_frame(max_edge=1280)
    assert (frame.width, frame.height) == (720, 1280)


def test_scale_maps_image_space_back_to_screen_space(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((1920, 1080)))
    frame = capture.capture_frame(max_edge=1280)
    assert frame.scale == pytest.approx(1.5)
    # A click at the centre of the scaled image is the centre of the screen.
    assert round(640 * frame.scale) == 960
    assert round(360 * frame.scale) == 540


def test_no_upscaling_when_screen_is_smaller_than_max_edge(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((800, 600)))
    frame = capture.capture_frame(max_edge=1280)
    assert (frame.width, frame.height) == (800, 600)
    assert frame.scale == pytest.approx(1.0)


def test_max_edge_zero_keeps_native_resolution(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((1920, 1080)))
    frame = capture.capture_frame(max_edge=0)
    assert (frame.width, frame.height) == (1920, 1080)


def test_rgba_screens_are_converted_before_jpeg_encoding(monkeypatch):
    """ImageGrab returns RGBA on some Windows configurations (layered
    windows); JPEG cannot encode alpha, so encoding would raise."""
    monkeypatch.setattr(capture, "_grab", _fake_grab((640, 480), mode="RGBA"))
    frame = capture.capture_frame(max_edge=0)
    assert Image.open(io.BytesIO(frame.payload)).format == "JPEG"


def test_payload_is_decodable_jpeg_of_the_reported_size(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((1920, 1080)))
    frame = capture.capture_frame(max_edge=1280)
    decoded = Image.open(io.BytesIO(frame.payload))
    assert decoded.format == "JPEG"
    assert decoded.size == (frame.width, frame.height)
    assert frame.mime == "image/jpeg"


def test_jpeg_quality_is_clamped_to_a_valid_range(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((320, 240)))
    # Out-of-range values must not raise out of PIL.
    for quality in (0, -5, 200):
        frame = capture.capture_frame(max_edge=0, jpeg_quality=quality)
        assert Image.open(io.BytesIO(frame.payload)).format == "JPEG"


def test_lower_quality_produces_a_smaller_payload(monkeypatch):
    # Noise, so JPEG quality actually changes the encoded size.
    import random

    random.seed(0)
    noisy = Image.new("RGB", (400, 400))
    noisy.putdata([
        (random.randrange(256), random.randrange(256), random.randrange(256))
        for _ in range(400 * 400)
    ])
    monkeypatch.setattr(capture, "_grab", lambda all_screens=True: noisy)

    low = capture.capture_frame(max_edge=0, jpeg_quality=20)
    high = capture.capture_frame(max_edge=0, jpeg_quality=90)
    assert len(low.payload) < len(high.payload)


# ------------------------------------------------------------------
# Config resolution - control must stay off unless explicitly enabled
# ------------------------------------------------------------------

def test_control_defaults_to_disabled(monkeypatch):
    from helpers import plugins

    monkeypatch.setattr(plugins, "get_plugin_config", lambda *a, **k: {})
    cfg = capture.get_config()
    assert cfg["control_enabled"] is False
    assert cfg["capture_enabled"] is True


def test_missing_plugin_config_does_not_raise(monkeypatch):
    from helpers import plugins

    monkeypatch.setattr(plugins, "get_plugin_config", lambda *a, **k: None)
    cfg = capture.get_config()
    assert cfg["control_enabled"] is False


def test_config_values_are_coerced(monkeypatch):
    from helpers import plugins

    monkeypatch.setattr(
        plugins,
        "get_plugin_config",
        lambda *a, **k: {
            "capture_max_edge": "800",
            "capture_jpeg_quality": "45",
            "control_enabled": True,
        },
    )
    cfg = capture.get_config()
    assert cfg["capture_max_edge"] == 800
    assert cfg["capture_jpeg_quality"] == 45
    assert cfg["control_enabled"] is True


# ------------------------------------------------------------------
# Multi-monitor capture
# ------------------------------------------------------------------

def test_capture_spans_all_screens_by_default(monkeypatch):
    """A primary-only grab left the agent unable to see two thirds of a
    three-monitor desktop."""
    seen = {}

    def _grab(all_screens: bool = True):
        seen["all_screens"] = all_screens
        return Image.new("RGB", (5760, 1080))

    monkeypatch.setattr(capture, "_grab", _grab)
    frame = capture.capture_frame(max_edge=1920)
    assert seen["all_screens"] is True
    assert (frame.screen_width, frame.screen_height) == (5760, 1080)


def test_wide_virtual_desktop_scales_by_its_long_edge(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((5760, 1080)))
    frame = capture.capture_frame(max_edge=1920)
    assert (frame.width, frame.height) == (1920, 360)
    # Scale must reflect the virtual desktop, or clicks land a monitor off.
    assert frame.scale == pytest.approx(3.0)


def test_primary_only_capture_can_be_requested(monkeypatch):
    seen = {}

    def _grab(all_screens: bool = True):
        seen["all_screens"] = all_screens
        return Image.new("RGB", (1920, 1080))

    monkeypatch.setattr(capture, "_grab", _grab)
    capture.capture_frame(max_edge=0, all_screens=False)
    assert seen["all_screens"] is False


def test_all_screens_config_defaults_to_true(monkeypatch):
    from helpers import plugins

    monkeypatch.setattr(plugins, "get_plugin_config", lambda *a, **k: {})
    assert capture.get_config()["capture_all_screens"] is True


# ------------------------------------------------------------------
# Per-monitor cropping
# ------------------------------------------------------------------

def test_monitor_crop_reports_its_offset(monkeypatch):
    """The offset is what lets a click on a cropped frame map back to the
    right screen; without it every click lands on the leftmost monitor."""
    monkeypatch.setattr(capture, "_grab", _fake_grab((5760, 1080)))
    monkeypatch.setattr(capture, "list_monitors", lambda: [
        {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": False},
        {"index": 1, "x": 1920, "y": 0, "width": 1920, "height": 1080, "primary": True},
        {"index": 2, "x": 3840, "y": 0, "width": 1920, "height": 1080, "primary": False},
    ])
    frame = capture.capture_frame(max_edge=0, monitor=2)
    assert (frame.width, frame.height) == (1920, 1080)
    assert (frame.offset_x, frame.offset_y) == (3840, 0)


def test_full_desktop_has_no_offset(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((5760, 1080)))
    frame = capture.capture_frame(max_edge=0)
    assert (frame.offset_x, frame.offset_y) == (0, 0)
    assert (frame.width, frame.height) == (5760, 1080)


def test_out_of_range_monitor_raises(monkeypatch):
    monkeypatch.setattr(capture, "_grab", _fake_grab((5760, 1080)))
    monkeypatch.setattr(capture, "list_monitors", lambda: [
        {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": True},
    ])
    with pytest.raises(ValueError):
        capture.capture_frame(monitor=5)


def test_monitors_are_ordered_left_to_right():
    """Windows enumerates monitors in an arbitrary order - on the
    development machine the rightmost screen comes second - so a positional
    label built from the raw order would mislabel screens."""
    monitors = capture.list_monitors()
    xs = [m["x"] for m in monitors]
    assert xs == sorted(xs)
    assert [m["index"] for m in monitors] == list(range(len(monitors)))


def test_code_defaults_match_the_shipped_yaml():
    """get_plugin_config returns only values that have been explicitly set,
    so the YAML defaults are never merged in and the code fallbacks are what
    actually apply. A mismatch means the documented default silently loses -
    capture_max_edge shipped as 1920 while the code used 1280."""
    import yaml

    from helpers import files

    shipped = yaml.safe_load(
        files.read_file("plugins/_win_desktop/default_config.yaml")
    )
    for key, value in capture._DEFAULTS.items():
        assert key in shipped, f"{key} missing from default_config.yaml"
        assert shipped[key] == value, (
            f"{key}: yaml says {shipped[key]!r}, code falls back to {value!r}"
        )
