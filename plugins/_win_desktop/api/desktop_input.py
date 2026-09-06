"""Mouse and keyboard input from the desktop viewer panel.

Separate from tools/desktop_control.py on purpose. That tool gates the
*agent*; this gates the *browser*, and the two callers are different
principals - the person watching the panel is the signed-in user acting
directly, not a model whose next action is a prediction.

The gates are nonetheless the same three, enforced here rather than
inherited, because helpers/input_control performs no permission checks of
its own and a second entry point that skipped them would silently undo
them for everyone:

1. control_enabled  - opt-in config, default false.
2. kill switch      - refuses while tripped.
3. audit log        - every accepted action recorded before it is performed.

Coordinates arrive in the coordinate space of the streamed image, which is
downscaled (1280px by default) from a 1920x1080 screen. They are scaled
back here from the frame dimensions the client reports, so a click on the
panel lands where the user aimed it.
"""

from __future__ import annotations

from helpers import audit_log, kill_switch
from helpers.api import ApiHandler, Request
from plugins._win_desktop.helpers import capture, input_control


class DesktopInput(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        cfg = capture.get_config(None)
        if not cfg["control_enabled"]:
            return {
                "ok": False,
                "error": (
                    "Desktop control is disabled. Enable 'control_enabled' in "
                    "the Windows Desktop plugin settings."
                ),
            }
        if kill_switch.is_tripped():
            return {"ok": False, "error": kill_switch.denial_message()}

        action = str(input.get("action") or "").strip().lower()
        if action not in (
            "move", "click", "scroll", "type", "key",
            "drag", "clipboard_get", "clipboard_set",
        ):
            return {"ok": False, "error": f"Unsupported action: {action!r}"}

        await audit_log.append_record(
            {
                "tool": "desktop_input",
                "agent_role": "webui",
                "action": action,
                # Clipboard text is not copied into the log: the record
                # exists to show an action happened, not to duplicate
                # whatever the user had copied.
                "arguments": {
                    k: ("<redacted>" if k == "text" else v)
                    for k, v in input.items()
                    if k != "action"
                },
                "context": "viewer-panel",
            }
        )

        try:
            result = self._dispatch(action, input)
            if action == "clipboard_get":
                return {"ok": True, "text": result}
            return {"ok": True, "message": result}
        except input_control.InputError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"input failed: {exc}"}

    def _screen_coords(self, data: dict) -> tuple[int, int]:
        """Map a click on the streamed image back to desktop pixels.

        Two transforms, in order: the frame is a scaled rendering, and it may
        also be a crop of one monitor. Scaling alone would put every click on
        the leftmost screen when a different monitor is being viewed.
        """
        try:
            x = float(data["x"])
            y = float(data["y"])
        except (KeyError, TypeError, ValueError):
            raise input_control.InputError("x and y are required")

        frame_w = float(data.get("frame_width") or 0)
        frame_h = float(data.get("frame_height") or 0)
        screen_w, screen_h = input_control.get_screen_size()
        # Absent or nonsensical frame dimensions mean the client didn't
        # report them; treating the coordinates as already-screen-space is
        # the only safe reading, and _to_absolute still range-checks them.
        monitor = data.get("monitor")
        if monitor not in (None, "", "all"):
            try:
                chosen = input_control.list_monitors()[int(monitor)]
            except (TypeError, ValueError, IndexError):
                raise input_control.InputError(f"unknown monitor {monitor!r}")
            source_w, source_h = chosen["width"], chosen["height"]
            offset_x, offset_y = chosen["x"], chosen["y"]
        else:
            source_w, source_h = screen_w, screen_h
            offset_x = offset_y = 0

        if frame_w > 0 and frame_h > 0:
            x = x * source_w / frame_w
            y = y * source_h / frame_h
        return int(round(x + offset_x)), int(round(y + offset_y))

    def _dispatch(self, action: str, data: dict) -> str:
        if action == "move":
            x, y = self._screen_coords(data)
            input_control.move(x, y)
            return f"moved to ({x}, {y})"

        if action == "click":
            x, y = self._screen_coords(data)
            button = str(data.get("button") or "left")
            clicks = int(data.get("clicks") or 1)
            input_control.click(x, y, button=button, clicks=clicks)
            return f"clicked {button} x{clicks} at ({x}, {y})"

        if action == "drag":
            start = self._screen_coords(data)
            end = self._screen_coords(
                {**data, "x": data.get("to_x"), "y": data.get("to_y")}
            )
            button = str(data.get("button") or "left")
            input_control.drag(*start, *end, button=button)
            return f"dragged {button} {start} -> {end}"

        if action == "clipboard_get":
            return input_control.get_clipboard_text()

        if action == "clipboard_set":
            text = data.get("text")
            if not isinstance(text, str):
                raise input_control.InputError("text is required")
            input_control.set_clipboard_text(text)
            return f"clipboard set ({len(text)} characters)"

        if action == "scroll":
            x, y = self._screen_coords(data)
            amount = int(data.get("amount") or 0)
            if not amount:
                raise input_control.InputError("amount is required")
            input_control.scroll(x, y, amount)
            return f"scrolled {amount} at ({x}, {y})"

        if action == "type":
            text = data.get("text")
            if not isinstance(text, str) or not text:
                raise input_control.InputError("text is required")
            input_control.type_text(text)
            return f"typed {len(text)} characters"

        keys = data.get("keys")
        if not isinstance(keys, str) or not keys.strip():
            raise input_control.InputError("keys is required")
        input_control.press_keys(keys)
        return f"pressed {keys}"
