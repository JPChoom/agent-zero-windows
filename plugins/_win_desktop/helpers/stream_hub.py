"""One capture loop per stream setting, shared by every viewer.

Before this, each open viewer ran its own grab/resize/encode loop, so two
tabs cost twice the CPU, and an unchanged screen was still re-encoded and
re-sent up to 10 times a second. Measured on a three-monitor 5760x1080
desktop (2026-10-10): grab ~66ms, resize ~24ms, encode ~3ms, ~55KB per frame.
So the CPU saving comes from sharing the loop and slowing it while the
screen is idle; skipping unchanged frames mainly saves bandwidth.

- Change detection compares a checksum of the *scaled* image, i.e. exactly
  what the viewer would see. A change too small to survive the downscale is
  invisible in the stream anyway.
- After IDLE_AFTER seconds without a change the loop polls at IDLE_FPS;
  any change, or input sent from the viewer (poke), restores full speed.
- An unchanged frame is re-sent every KEEPALIVE_SECONDS so tunnels and
  proxies do not close a quiet stream and a stalled viewer recovers.
- The capture thread runs below normal priority, so a busy machine's real
  work wins over the stream.
- A producer stops LINGER_SECONDS after its last viewer leaves.
"""

from __future__ import annotations

import threading
import time
import zlib
from dataclasses import dataclass

from plugins._win_desktop.helpers import capture

IDLE_AFTER = 3.0
IDLE_FPS = 1.0
KEEPALIVE_SECONDS = 10.0
LINGER_SECONDS = 5.0
ERROR_BACKOFF = 0.5


@dataclass(frozen=True)
class StreamKey:
    max_edge: int
    jpeg_quality: int
    fps: float
    all_screens: bool
    monitor: int | None
    show_cursor: bool


class _Producer:
    def __init__(self, key: StreamKey):
        self.key = key
        self.cond = threading.Condition()
        self.wake = threading.Event()
        self.frame: capture.CapturedFrame | None = None
        self.seq = 0
        self.viewers = 0
        self.idle_since: float | None = None
        self.last_change = time.monotonic()
        self.running = True
        self.thread = threading.Thread(
            target=self._run, name=f"desktop-stream-{id(self):x}", daemon=True
        )

    def poke(self) -> None:
        self.last_change = time.monotonic()
        self.wake.set()

    def _run(self) -> None:
        _lower_thread_priority()
        key = self.key
        last_sig = None
        last_publish = 0.0
        while self.running:
            started = time.monotonic()
            try:
                prepared = capture.prepare_image(
                    max_edge=key.max_edge,
                    all_screens=key.all_screens,
                    monitor=key.monitor,
                    show_cursor=key.show_cursor,
                )
                sig = (prepared.image.size, zlib.crc32(prepared.image.tobytes()))
                now = time.monotonic()
                changed = sig != last_sig
                if changed:
                    self.last_change = now
                if changed or now - last_publish >= KEEPALIVE_SECONDS:
                    frame = capture.encode_image(prepared, key.jpeg_quality)
                    with self.cond:
                        self.frame = frame
                        self.seq += 1
                        self.cond.notify_all()
                    last_sig = sig
                    last_publish = now
            except Exception:
                # A transient grab failure (screen locked, display mode
                # change) must not stop the stream.
                self.wake.wait(ERROR_BACKOFF)
                self.wake.clear()
                continue

            now = time.monotonic()
            idle = now - self.last_change >= IDLE_AFTER
            interval = 1.0 / (IDLE_FPS if idle else max(0.1, key.fps))
            remaining = interval - (now - started)
            if remaining > 0:
                self.wake.wait(remaining)
            self.wake.clear()

    def next_frame(self, after_seq: int, timeout: float):
        """Wait for a frame newer than after_seq; (None, after_seq) on timeout."""
        with self.cond:
            if self.seq <= after_seq:
                self.cond.wait(timeout)
            if self.seq <= after_seq or self.frame is None:
                return None, after_seq
            return self.frame, self.seq


_lock = threading.Lock()
_producers: dict[StreamKey, _Producer] = {}


def subscribe(key: StreamKey) -> _Producer:
    with _lock:
        producer = _producers.get(key)
        if producer is None or not producer.running:
            producer = _Producer(key)
            _producers[key] = producer
            producer.thread.start()
        producer.viewers += 1
        producer.idle_since = None
        return producer


def unsubscribe(producer: _Producer) -> None:
    with _lock:
        producer.viewers = max(0, producer.viewers - 1)
        if producer.viewers == 0:
            producer.idle_since = time.monotonic()
            timer = threading.Timer(LINGER_SECONDS, _stop_if_unused, args=(producer,))
            timer.daemon = True
            timer.start()


def _stop_if_unused(producer: _Producer) -> None:
    with _lock:
        if producer.viewers or producer.idle_since is None:
            return
        if time.monotonic() - producer.idle_since < LINGER_SECONDS - 0.05:
            return
        producer.running = False
        producer.wake.set()
        if _producers.get(producer.key) is producer:
            del _producers[producer.key]


def poke() -> None:
    """Viewer input arrived: capture at full speed now rather than at the idle rate."""
    with _lock:
        producers = list(_producers.values())
    for producer in producers:
        producer.poke()


def active_streams() -> int:
    with _lock:
        return len(_producers)


def _lower_thread_priority() -> None:
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        THREAD_PRIORITY_BELOW_NORMAL = -1
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL)
    except Exception:
        pass
