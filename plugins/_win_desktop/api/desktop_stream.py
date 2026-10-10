"""MJPEG stream of the live Windows desktop.

Served as multipart/x-mixed-replace, which browsers render natively in a
plain <img> tag. That is the whole reason this needs no streaming protocol,
no WebSocket framing and no client-side decoder - the alternative designs
(Xpra, noVNC + websockify, Guacamole) all require an external daemon, and
this fork already has everything needed to produce JPEG frames.

GET rather than POST because an <img src> can only issue a GET. Auth is
still required: the browser sends the session cookie with the image
request like any other subresource.
"""

from __future__ import annotations

import time

from flask import Response

from helpers.api import ApiHandler, Request
from plugins._win_desktop.helpers import capture, stream_hub


BOUNDARY = "a0desktopframe"

# Bandwidth presets, chosen per connection. A three-monitor desktop at high
# quality is several hundred KB per frame, which a remote link over a tunnel
# will not sustain - hence a visible control rather than a fixed setting.
QUALITY_PRESETS = {
    "high": {"max_edge": 2560, "jpeg_quality": 80, "fps": 12},
    "medium": {"max_edge": 1920, "jpeg_quality": 60, "fps": 10},
    "low": {"max_edge": 1280, "jpeg_quality": 40, "fps": 5},
}

# Upper bound on frame rate while the screen is changing. The shared loop
# (helpers/stream_hub) drops to ~1fps when nothing changes and skips frames
# identical to the last one sent.
MAX_FPS = 10

# A viewer left open forever would hold a worker thread indefinitely. The
# panel reconnects automatically - an <img> re-requests when the stream
# ends - so a bounded stream costs the viewer nothing and releases the
# thread if the tab is abandoned.
STREAM_SECONDS = 300


class DesktopStream(ApiHandler):

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET"]

    @classmethod
    def requires_csrf(cls) -> bool:
        # A CSRF token cannot be attached to an <img src>. This endpoint is
        # read-only and returns no data an attacker could read cross-origin
        # (the browser will not let a foreign page read image pixels), so
        # the exchange is safe; every state-changing action lives in
        # desktop_input, which does require CSRF.
        return False

    async def process(self, input: dict, request: Request) -> Response:
        cfg = capture.get_config(None)
        if not cfg["capture_enabled"]:
            return Response("desktop capture is disabled", status=409,
                            mimetype="text/plain")

        # ?monitors=1 returns the monitor list instead of a stream, so the
        # panel can build its selector without a second endpoint.
        if str(request.args.get("monitors", "")).strip() in ("1", "true", "yes"):
            import json

            return Response(
                json.dumps({"monitors": capture.list_monitors()}),
                mimetype="application/json",
            )

        monitor = request.args.get("monitor")
        try:
            monitor_index = int(monitor) if monitor not in (None, "", "all") else None
        except (TypeError, ValueError):
            return Response("invalid monitor", status=400, mimetype="text/plain")

        preset = QUALITY_PRESETS.get(str(request.args.get("quality", "")).lower())
        if preset:
            quality = preset["jpeg_quality"]
            max_edge = preset["max_edge"]
            max_fps = preset["fps"]
        else:
            # No preset asked for: fall back to the configured values.
            quality = cfg["capture_jpeg_quality"]
            max_edge = cfg["capture_max_edge"]
            max_fps = MAX_FPS
        all_screens = cfg["capture_all_screens"]
        show_cursor = cfg["capture_cursor"]

        key = stream_hub.StreamKey(
            max_edge=max_edge,
            jpeg_quality=quality,
            fps=max_fps,
            all_screens=all_screens,
            monitor=monitor_index,
            show_cursor=show_cursor,
        )
        if monitor_index is not None:
            # Fail fast with a 400 instead of a stream that never yields.
            try:
                count = len(capture.list_monitors())
            except Exception:
                count = monitor_index + 1
            if not 0 <= monitor_index < count:
                return Response("invalid monitor", status=400, mimetype="text/plain")

        def frames():
            # Viewers share one capture loop per setting (helpers/stream_hub).
            # Each part is followed immediately by the next boundary, so a
            # browser shows a frame as soon as it arrives even when the next
            # one is seconds away (unchanged frames are not re-sent).
            producer = stream_hub.subscribe(key)
            try:
                yield f"--{BOUNDARY}\r\n".encode("ascii")
                deadline = time.time() + STREAM_SECONDS
                seq = 0
                while time.time() < deadline:
                    frame, seq = producer.next_frame(seq, timeout=1.0)
                    if frame is None:
                        continue
                    yield (
                        f"Content-Type: {frame.mime}\r\n"
                        f"Content-Length: {len(frame.payload)}\r\n"
                        f"X-Screen-Width: {frame.screen_width}\r\n"
                        f"X-Screen-Height: {frame.screen_height}\r\n"
                        # Where this frame sits in the desktop when a single
                        # monitor is cropped out. The panel maps clicks using
                        # the monitor index it asked for rather than these,
                        # but they make a captured stream self-describing when
                        # debugging a click that landed on the wrong screen.
                        f"X-Offset-X: {frame.offset_x}\r\n"
                        f"X-Offset-Y: {frame.offset_y}\r\n\r\n"
                    ).encode("ascii") + frame.payload + f"\r\n--{BOUNDARY}\r\n".encode("ascii")
            finally:
                stream_hub.unsubscribe(producer)

        return Response(
            frames(),
            mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store, no-cache", "Pragma": "no-cache"},
        )
