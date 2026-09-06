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

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


@dataclass(frozen=True)
class CapturedFrame:
    payload: bytes
    mime: str
    width: int
    height: int
    # Native size of the captured area before any downscale - the stream
    # endpoint needs this to map click coordinates from the scaled image
    # back to the real desktop. This is the whole virtual desktop when
    # multiple monitors are present, not just the primary screen.
    screen_width: int
    screen_height: int
    # Where this frame sits in the 0-based virtual desktop. Non-zero when a
    # single monitor was cropped out; a click at frame (0, 0) then means
    # desktop (offset_x, offset_y), not the desktop's own corner.
    offset_x: int = 0
    offset_y: int = 0

    @property
    def scale(self) -> float:
        """Multiply a captured-image coordinate by this to reach screen space."""
        if not self.width:
            return 1.0
        return self.screen_width / self.width


def get_virtual_bounds() -> tuple[int, int, int, int]:
    """(origin_x, origin_y, width, height) of the whole virtual desktop.

    The origin is NOT always (0, 0): a monitor arranged to the left of the
    primary one gives a negative SM_XVIRTUALSCREEN (measured -1920 on the
    development machine). Callers work in 0-based capture coordinates and
    this offset is what converts them to Windows' virtual-screen space.
    """
    import ctypes

    user32 = ctypes.WinDLL("user32")
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def _grab(all_screens: bool = True):
    # Imported lazily so this module can be imported on non-Windows hosts
    # (e.g. to run the tests) without a display present.
    from PIL import ImageGrab

    # all_screens spans every monitor. Without it a multi-monitor desktop is
    # captured as the primary screen only - which left the agent unable to
    # see, or to click on, two thirds of a three-monitor setup.
    return ImageGrab.grab(all_screens=all_screens)


def capture_frame(
    max_edge: int = 1280,
    jpeg_quality: int = 60,
    all_screens: bool = True,
    monitor: int | None = None,
) -> CapturedFrame:
    """Grab the desktop and return it as JPEG bytes.

    Spans every monitor by default. Pass `monitor` (an index from
    list_monitors) to crop to one screen - a three-monitor desktop is
    5760x1080, and scaled to fit a panel each screen becomes too small to
    read, so viewing one at a time is the practical mode.

    max_edge <= 0 keeps native resolution.
    """
    from PIL import Image

    image = _grab(all_screens)
    offset_x = offset_y = 0

    if monitor is not None:
        monitors = list_monitors()
        if not 0 <= monitor < len(monitors):
            raise ValueError(
                f"monitor {monitor} does not exist (found {len(monitors)})"
            )
        chosen = monitors[monitor]
        offset_x, offset_y = chosen["x"], chosen["y"]
        image = image.crop(
            (
                offset_x,
                offset_y,
                offset_x + chosen["width"],
                offset_y + chosen["height"],
            )
        )

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
        offset_x=offset_x,
        offset_y=offset_y,
    )


# Fallbacks used when a key is absent from the stored plugin config. These
# must match default_config.yaml: get_plugin_config returns only values that
# have actually been set, so the YAML defaults are not merged in and a
# mismatch here silently wins over the documented default.
_DEFAULTS = {
    "capture_enabled": True,
    "capture_max_edge": 1920,
    "capture_jpeg_quality": 60,
    "capture_all_screens": True,
    "control_enabled": False,
}


def get_config(agent=None) -> dict:
    from helpers import plugins

    cfg = plugins.get_plugin_config("_win_desktop", agent=agent) or {}
    return {
        "capture_enabled": bool(
            cfg.get("capture_enabled", _DEFAULTS["capture_enabled"])
        ),
        "capture_max_edge": int(
            cfg.get("capture_max_edge", _DEFAULTS["capture_max_edge"]) or 0
        ),
        "capture_jpeg_quality": int(
            cfg.get("capture_jpeg_quality", _DEFAULTS["capture_jpeg_quality"]) or 60
        ),
        "capture_all_screens": bool(
            cfg.get("capture_all_screens", _DEFAULTS["capture_all_screens"])
        ),
        "control_enabled": bool(
            cfg.get("control_enabled", _DEFAULTS["control_enabled"])
        ),
    }


def list_monitors() -> list[dict]:
    """Monitors in 0-based virtual-desktop coordinates, ordered left to right.

    Windows' own enumeration order is not spatial - on the development
    machine the rightmost screen enumerates second - so entries are sorted
    by x and given a stable index for the UI to label. Coordinates are
    0-based (virtual-desktop origin subtracted) to match capture_frame's
    output and desktop_control's input, rather than Windows' signed space.
    """
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(RECT), wintypes.LPARAM,
    )
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    found: list[tuple[int, int, int, int]] = []

    def _collect(_hmon, _hdc, lprect, _lparam):
        rect = lprect.contents
        found.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    # The callback must stay referenced for the duration of the call.
    callback = proc(_collect)
    user32.EnumDisplayMonitors(None, None, callback, 0)

    origin_x, origin_y, _, _ = get_virtual_bounds()
    monitors = []
    for left, top, right, bottom in sorted(found, key=lambda r: (r[0], r[1])):
        monitors.append(
            {
                "x": left - origin_x,
                "y": top - origin_y,
                "width": right - left,
                "height": bottom - top,
                # The primary monitor is the one containing Windows' (0, 0).
                "primary": left <= 0 < right and top <= 0 < bottom,
            }
        )
    for index, monitor in enumerate(monitors):
        monitor["index"] = index
    return monitors
