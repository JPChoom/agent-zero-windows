"""Agent-facing tool: capture the real Windows desktop so the model can see it.

Read-only - it never moves the mouse or presses a key (see
tools/desktop_control.py for that, which is opt-in).

The captured frame is attached the same way tools/vision_load.py attaches
images: a text tool-result for the transcript, plus a separate
history.RawMessage carrying an `image_url` data URI, so vision-capable
models actually receive the pixels. Writing a file into the workdir was the
alternative and is worse - it would clutter the project and raise a
containment question for a screenshot that is only meaningful for one turn.
"""

from __future__ import annotations

import base64

from helpers import history
from helpers.print_style import PrintStyle
from helpers.tool import Response, Tool
from plugins._win_desktop.helpers import capture


# Matches tools/vision_load.py. Vision models bill images by tile count, not
# by base64 length, so the encoded size is not a usable estimate.
TOKENS_ESTIMATE = 1500


class DesktopScreenshot(Tool):

    async def execute(self, **kwargs) -> Response:
        await self.agent.handle_intervention()

        self.frame = None
        cfg = capture.get_config(self.agent)

        if not cfg["capture_enabled"]:
            return Response(
                message=(
                    "Desktop capture is disabled. Enable 'capture_enabled' in the "
                    "Windows Desktop plugin settings to use this tool."
                ),
                break_loop=False,
            )

        try:
            self.frame = capture.capture_frame(
                max_edge=cfg["capture_max_edge"],
                jpeg_quality=cfg["capture_jpeg_quality"],
            )
        except Exception as exc:
            return Response(
                message=f"Could not capture the desktop: {exc}", break_loop=False
            )

        # Screen resolution is stated explicitly because desktop_control acts
        # in native screen coordinates: a model that reasons from the
        # downscaled image's dimensions would click in the wrong place.
        message = (
            "Desktop screenshot captured.\n"
            f"Screen resolution: {self.frame.screen_width}x{self.frame.screen_height}\n"
            f"Image attached at: {self.frame.width}x{self.frame.height}\n"
            "Any click or move coordinates must be given in screen space "
            f"({self.frame.screen_width}x{self.frame.screen_height})."
        )
        return Response(message=message, break_loop=False)

    async def after_execution(self, response: Response, **kwargs):
        log_id = self.log.id if self.log else ""
        self.agent.hist_add_tool_result(self.name, response.message, id=log_id)

        if not self.frame:
            return

        data_uri = (
            f"data:{self.frame.mime};base64,"
            + base64.b64encode(self.frame.payload).decode("ascii")
        )
        raw = history.RawMessage(
            raw_content=[{"type": "image_url", "image_url": {"url": data_uri}}],
            preview="<Windows desktop screenshot>",
        )
        self.agent.hist_add_message(False, content=raw, tokens=TOKENS_ESTIMATE)

        PrintStyle(
            font_color="#1B4F72", background_color="white", padding=True, bold=True
        ).print(f"{self.agent.agent_name}: Response from tool '{self.name}'")
        PrintStyle(font_color="#85C1E9").print(response.message)
