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
from plugins._win_desktop.helpers import capture


BOUNDARY = "a0desktopframe"

# Upper bound on frame rate. Measured cost of a grab plus resize/encode is
# ~80ms (~12fps), so this caps rather than paces the common case; it exists
# to stop a fast machine spending the whole core on frames nobody watches.
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

        quality = cfg["capture_jpeg_quality"]
        max_edge = cfg["capture_max_edge"]
        all_screens = cfg["capture_all_screens"]

        def frames():
            deadline = time.time() + STREAM_SECONDS
            min_interval = 1.0 / MAX_FPS
            while time.time() < deadline:
                started = time.time()
                try:
                    frame = capture.capture_frame(
                        max_edge=max_edge,
                        jpeg_quality=quality,
                        all_screens=all_screens,
                        monitor=monitor_index,
                    )
                except Exception:
                    # A transient grab failure (screen locked, display mode
                    # change) must not tear down the viewer.
                    time.sleep(0.5)
                    continue
                yield (
                    f"--{BOUNDARY}\r\n"
                    f"Content-Type: {frame.mime}\r\n"
                    f"Content-Length: {len(frame.payload)}\r\n"
                    f"X-Screen-Width: {frame.screen_width}\r\n"
                    f"X-Screen-Height: {frame.screen_height}\r\n"
                    # Where this frame sits in the desktop when a single
                    # monitor is cropped out. The panel maps clicks using the
                    # monitor index it asked for rather than these, but they
                    # make a captured stream self-describing when debugging a
                    # click that landed on the wrong screen.
                    f"X-Offset-X: {frame.offset_x}\r\n"
                    f"X-Offset-Y: {frame.offset_y}\r\n\r\n"
                ).encode("ascii") + frame.payload + b"\r\n"
                elapsed = time.time() - started
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)

        return Response(
            frames(),
            mimetype=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store, no-cache", "Pragma": "no-cache"},
        )
