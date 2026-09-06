"""Agent-facing tool: drive the real Windows desktop (mouse and keyboard).

This is the one genuinely dangerous surface in this plugin. Synthetic
clicks and keystrokes never pass through _safety_policy, which inspects
terminal *command text* - so an agent with input can do anything the
signed-in user can (dismiss a UAC prompt, drive a browser, operate any
open application) with none of that plugin's deny categories applying.

Three independent gates, checked here rather than in helpers/input_control
so the web endpoint can enforce them separately for its own caller:

1. control_enabled  - opt-in config, default false.
2. kill switch      - refuses while tripped, same as code_execution_tool.
3. audit log        - every accepted action is appended to the hash-chained
                      log before it is performed, so the record survives
                      even if the action crashes the session.
"""

from __future__ import annotations

from helpers import audit_log, kill_switch
from helpers.tool import Response, Tool
from plugins._win_desktop.helpers import capture, input_control


class DesktopControl(Tool):

    async def execute(self, action: str = "", **kwargs) -> Response:
        await self.agent.handle_intervention()

        cfg = capture.get_config(self.agent)
        if not cfg["control_enabled"]:
            return Response(
                message=(
                    "Desktop control is disabled. It is off by default because "
                    "synthetic input bypasses the command safety policy. Enable "
                    "'control_enabled' in the Windows Desktop plugin settings to "
                    "allow it."
                ),
                break_loop=False,
            )

        if kill_switch.is_tripped():
            return Response(message=kill_switch.denial_message(), break_loop=False)

        action = str(action or "").strip().lower()
        handlers = {
            "focus": self._focus,
            "move": self._move,
            "click": self._click,
            "scroll": self._scroll,
            "type": self._type,
            "key": self._key,
        }
        handler = handlers.get(action)
        if not handler:
            return Response(
                message=(
                    f"Unknown action {action!r}. Use one of: "
                    f"{', '.join(sorted(handlers))}."
                ),
                break_loop=False,
            )

        # Focus the requested window before auditing, so the record names
        # where the input actually went rather than where it was aimed.
        # Raising a window is itself harmless - it changes no data - and an
        # audit entry that records the wrong target would be worse.
        window = kwargs.get("window")
        try:
            if window:
                focused = input_control.focus_window(str(window))
            else:
                _, focused = input_control.get_foreground_window()
        except input_control.InputError as exc:
            return Response(message=f"Invalid request: {exc}", break_loop=False)

        await audit_log.append_record(
            {
                "tool": "desktop_control",
                "agent_role": getattr(self.agent, "agent_name", ""),
                "action": action,
                "arguments": {k: v for k, v in kwargs.items() if k != "action"},
                "target_window": focused,
                "targeted_explicitly": bool(window),
                "context": getattr(self.agent.context, "id", ""),
            }
        )

        try:
            message = handler(**kwargs)
        except input_control.InputError as exc:
            return Response(message=f"Invalid request: {exc}", break_loop=False)
        except Exception as exc:
            return Response(
                message=f"Desktop control failed: {exc}", break_loop=False
            )

        # Naming the receiving window matters even on success: input goes
        # wherever focus is, and a run that typed into a pre-existing
        # unsaved document looked identical to one that worked.
        target = f"\nInput went to: {focused!r}" if focused else ""
        if not window and action in ("type", "key"):
            target += (
                "\nNo window was named, so this went to whatever had focus. "
                "Pass `window` to target one explicitly."
            )

        return Response(
            message=(
                f"{message}{target}\nTake a desktop_screenshot to confirm the "
                "result before assuming it worked."
            ),
            break_loop=False,
        )

    # -- actions ----------------------------------------------------------

    def _focus(self, **kwargs) -> str:
        window = kwargs.get("window")
        if not isinstance(window, str) or not window.strip():
            raise input_control.InputError("window is required for the focus action")
        # focus_window already ran above; reaching here means it succeeded.
        return f"Brought the window matching {window!r} to the foreground."

    def _coords(self, kwargs: dict) -> tuple[int, int]:
        if "x" not in kwargs or "y" not in kwargs:
            raise input_control.InputError("x and y are required")
        try:
            return int(kwargs["x"]), int(kwargs["y"])
        except (TypeError, ValueError):
            raise input_control.InputError("x and y must be integers")

    def _move(self, **kwargs) -> str:
        x, y = self._coords(kwargs)
        input_control.move(x, y)
        return f"Moved the pointer to ({x}, {y})."

    def _click(self, **kwargs) -> str:
        x, y = self._coords(kwargs)
        button = kwargs.get("button", "left")
        clicks = kwargs.get("clicks", 1)
        input_control.click(x, y, button=button, clicks=clicks)
        label = {1: "Clicked", 2: "Double-clicked", 3: "Triple-clicked"}.get(
            int(clicks), "Clicked"
        )
        return f"{label} the {button} button at ({x}, {y})."

    def _scroll(self, **kwargs) -> str:
        x, y = self._coords(kwargs)
        if "amount" not in kwargs:
            raise input_control.InputError("amount is required (negative scrolls down)")
        try:
            amount = int(kwargs["amount"])
        except (TypeError, ValueError):
            raise input_control.InputError("amount must be an integer")
        input_control.scroll(x, y, amount)
        direction = "up" if amount > 0 else "down"
        return f"Scrolled {direction} {abs(amount)} notches at ({x}, {y})."

    def _type(self, **kwargs) -> str:
        text = kwargs.get("text")
        if not isinstance(text, str) or not text:
            raise input_control.InputError("text is required")
        input_control.type_text(text)
        return f"Typed {len(text)} characters."

    def _key(self, **kwargs) -> str:
        keys = kwargs.get("keys")
        if not isinstance(keys, str) or not keys.strip():
            raise input_control.InputError("keys is required, e.g. 'ctrl+c'")
        input_control.press_keys(keys)
        return f"Pressed {keys}."
