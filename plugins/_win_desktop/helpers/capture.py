"""Windows desktop capture.

Uses PIL's ImageGrab rather than adding a capture dependency (mss, dxcam):
measured on this fork's target hardware at 1920x1080, a full grab costs
~29ms and a resize+JPEG(q60) to 1280px costs ~50ms, i.e. ~12fps end to end
and ~70KB per frame. That is comfortably enough for both uses here - a
model reading a screen, and a human watching a monitoring panel - so the
extra dependency isn't justified.

Deliberately has no Agent Zero imports beyond helpers.plugins config, so it
stays unit-testable and reusable by both the agent-facing tool and the
MJPEG stream endpoint.
"""

from __future__ import annotations

import io
from dataclasses import dataclass


JPEG_MIME = "image/jpeg"


@dataclass(frozen=True)
class CapturedFrame:
    payload: bytes
    mime: str
    width: int
    height: int
    # Native screen size before any downscale - the stream endpoint needs
    # this to map click coordinates from the scaled image back to the real
    # desktop.
    screen_width: int
    screen_height: int

    @property
    def scale(self) -> float:
        """Multiply a captured-image coordinate by this to reach screen space."""
        if not self.width:
            return 1.0
        return self.screen_width / self.width


def _grab():
    # Imported lazily so this module can be imported on non-Windows hosts
    # (e.g. to run the tests) without a display present.
    from PIL import ImageGrab

    return ImageGrab.grab()


def capture_frame(
    max_edge: int = 1280,
    jpeg_quality: int = 60,
) -> CapturedFrame:
    """Grab the primary desktop and return it as JPEG bytes.

    max_edge <= 0 keeps the native resolution.
    """
    from PIL import Image

    image = _grab()
    screen_width, screen_height = image.size

    if max_edge and max(image.size) > max_edge:
        if image.width >= image.height:
            target = (max_edge, max(1, round(max_edge * image.height / image.width)))
        else:
            target = (max(1, round(max_edge * image.width / image.height)), max_edge)
        image = image.resize(target, Image.BILINEAR)

    # JPEG can't encode an alpha channel, and ImageGrab returns RGBA on some
    # Windows configurations (e.g. when a layered window is on screen).
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=max(1, min(95, int(jpeg_quality))))

    return CapturedFrame(
        payload=buffer.getvalue(),
        mime=JPEG_MIME,
        width=image.width,
        height=image.height,
        screen_width=screen_width,
        screen_height=screen_height,
    )


def get_config(agent=None) -> dict:
    from helpers import plugins

    cfg = plugins.get_plugin_config("_win_desktop", agent=agent) or {}
    return {
        "capture_enabled": bool(cfg.get("capture_enabled", True)),
        "capture_max_edge": int(cfg.get("capture_max_edge", 1280) or 0),
        "capture_jpeg_quality": int(cfg.get("capture_jpeg_quality", 60) or 60),
        "control_enabled": bool(cfg.get("control_enabled", False)),
    }
