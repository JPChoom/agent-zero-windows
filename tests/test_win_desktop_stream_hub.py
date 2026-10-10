"""Tests for plugins/_win_desktop/helpers/stream_hub.py (shared capture loop)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image

from plugins._win_desktop.helpers import capture, stream_hub


class FakeScreen:
    """Stands in for capture.prepare_image: counts grabs, changes on demand."""

    def __init__(self):
        self.color = (0, 0, 0)
        self.grabs = 0
        self.lock = threading.Lock()

    def prepare_image(self, max_edge=1280, all_screens=True, monitor=None, show_cursor=True):
        with self.lock:
            self.grabs += 1
            color = self.color
        return capture.PreparedImage(
            image=Image.new("RGB", (32, 18), color),
            screen_width=32,
            screen_height=18,
        )


@pytest.fixture
def screen(monkeypatch):
    fake = FakeScreen()
    monkeypatch.setattr(capture, "prepare_image", fake.prepare_image)
    monkeypatch.setattr(stream_hub, "IDLE_AFTER", 0.3)
    monkeypatch.setattr(stream_hub, "IDLE_FPS", 2.0)
    monkeypatch.setattr(stream_hub, "KEEPALIVE_SECONDS", 60.0)
    monkeypatch.setattr(stream_hub, "LINGER_SECONDS", 0.2)
    yield fake
    with stream_hub._lock:
        producers = list(stream_hub._producers.values())
        stream_hub._producers.clear()
    for producer in producers:
        producer.running = False
        producer.wake.set()
        producer.thread.join(timeout=2)


def _key(fps=20.0, monitor=None):
    return stream_hub.StreamKey(
        max_edge=1280, jpeg_quality=60, fps=fps,
        all_screens=True, monitor=monitor, show_cursor=True,
    )


def test_viewers_with_the_same_settings_share_one_loop(screen):
    a = stream_hub.subscribe(_key())
    b = stream_hub.subscribe(_key())
    assert a is b
    assert stream_hub.active_streams() == 1
    c = stream_hub.subscribe(_key(monitor=1))
    assert c is not a
    assert stream_hub.active_streams() == 2
    for p in (a, b, c):
        stream_hub.unsubscribe(p)


def test_unchanged_screen_is_not_resent(screen):
    producer = stream_hub.subscribe(_key())
    frame, seq = producer.next_frame(0, timeout=2)
    assert frame is not None and seq == 1
    time.sleep(0.3)
    assert screen.grabs > 2  # still polling
    frame, same = producer.next_frame(seq, timeout=0.2)
    assert frame is None and same == seq  # nothing new to send

    screen.color = (255, 0, 0)
    frame, seq2 = producer.next_frame(seq, timeout=2)
    assert frame is not None and seq2 == seq + 1
    stream_hub.unsubscribe(producer)


def test_idle_screen_drops_to_the_idle_rate_and_poke_restores_it(screen):
    producer = stream_hub.subscribe(_key(fps=20.0))
    producer.next_frame(0, timeout=2)
    time.sleep(0.5)  # past IDLE_AFTER
    before = screen.grabs
    time.sleep(1.0)
    idle_grabs = screen.grabs - before
    assert idle_grabs <= 4, idle_grabs  # ~2 fps, not ~20

    stream_hub.poke()
    before = screen.grabs
    time.sleep(0.25)
    assert screen.grabs - before >= 3  # back to full speed
    stream_hub.unsubscribe(producer)


def test_unchanged_frame_is_resent_as_a_keepalive(screen, monkeypatch):
    monkeypatch.setattr(stream_hub, "KEEPALIVE_SECONDS", 0.3)
    producer = stream_hub.subscribe(_key())
    _, seq = producer.next_frame(0, timeout=2)
    frame, seq2 = producer.next_frame(seq, timeout=2)
    assert frame is not None and seq2 > seq
    stream_hub.unsubscribe(producer)


def test_loop_stops_after_the_last_viewer_leaves(screen):
    producer = stream_hub.subscribe(_key())
    producer.next_frame(0, timeout=2)
    stream_hub.unsubscribe(producer)
    time.sleep(0.6)
    assert stream_hub.active_streams() == 0
    producer.thread.join(timeout=2)
    assert not producer.thread.is_alive()


def test_a_returning_viewer_keeps_the_loop(screen):
    producer = stream_hub.subscribe(_key())
    stream_hub.unsubscribe(producer)
    again = stream_hub.subscribe(_key())
    time.sleep(0.4)
    assert again is producer and producer.running
    stream_hub.unsubscribe(again)


def test_grab_failure_does_not_stop_the_loop(screen, monkeypatch):
    calls = {"n": 0}
    real = screen.prepare_image

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("screen locked")
        return real(**kwargs)

    monkeypatch.setattr(capture, "prepare_image", flaky)
    monkeypatch.setattr(stream_hub, "ERROR_BACKOFF", 0.05)
    producer = stream_hub.subscribe(_key())
    frame, _ = producer.next_frame(0, timeout=2)
    assert frame is not None
    stream_hub.unsubscribe(producer)
