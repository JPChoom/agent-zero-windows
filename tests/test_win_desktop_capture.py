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
    def _grab():
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
    monkeypatch.setattr(capture, "_grab", lambda: noisy)

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
