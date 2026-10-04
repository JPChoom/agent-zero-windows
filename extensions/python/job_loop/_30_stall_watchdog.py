"""Auto-nudge a running chat that has made no visible progress for a while.

"Progress" is the chat log's update counter (`len(context.log.updates)`,
the same `log_version` the WebUI polls): every log item created or
updated bumps it - streamed model output and reasoning, tool output,
warnings, approval prompts. A running chat whose counter hasn't moved in
STALL_SECONDS is treated as stuck and nudged, exactly as if the user had
pressed Nudge.

STALL_SECONDS sits well above the longest legitimate silent waits: the
safety-policy/permissions approval wait (300s default), the model
stream-idle timeout (models.DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS, 120s) and
code_execution_tool's 120s no-output return. A stall past all of those is
a wedge - e.g. a lost task wakeup, which no timeout inside the task can
ever fire for - not slow work.

Bounded so a chat that can't recover isn't nudged forever: at most
MAX_NUDGES_PER_WINDOW nudges per chat in any NUDGE_WINDOW_SECONDS, after
which the watchdog stops for that chat and raises a notification. Paused
chats are never nudged, and nothing is nudged while any Allow/Deny decision
is outstanding (plugins/_safety_policy/helpers/approval_registry.py - shared
by safety policy, permissions and infection-check clarification, whose
900s wait exceeds STALL_SECONDS); the stall window restarts after it.

Runs from helpers/job_loop.py once per SLEEP_TIME (60s), so a stall is
acted on between STALL_SECONDS and STALL_SECONDS + 60s after it began.
"""

import time
from typing import Any

from agent import AgentContext
from helpers.extension import Extension
from helpers.notification import NotificationManager, NotificationPriority, NotificationType
from helpers.print_style import PrintStyle
from plugins._safety_policy.helpers import approval_registry

STALL_SECONDS = 600
MAX_NUDGES_PER_WINDOW = 4
NUDGE_WINDOW_SECONDS = 2 * 60 * 60


def _progress_marker(context) -> tuple:
    log = context.log
    return (getattr(log, "guid", None), len(getattr(log, "updates", None) or []))


class StallWatchdog(Extension):
    # context id -> {"marker", "since", "nudges": [timestamps], "gave_up"}.
    # Class-level so it survives across job-loop passes (a new instance is
    # created per call); in-memory only, reset by a server restart.
    _state: dict[str, dict] = {}

    async def execute(self, data: dict[str, Any] | None = None, **kwargs):
        now = time.time()
        states = type(self)._state
        live_ids = set()
        # A chat blocked on an Allow/Deny prompt is waiting for the user, not
        # stuck - and those waits (infection-check clarification: 900s) can
        # outlast STALL_SECONDS. The registry is process-wide rather than
        # per chat, so while any decision is outstanding every running chat's
        # clock restarts; the stall window then counts from after the answer.
        decision_pending = approval_registry.has_pending()

        for context in list(AgentContext.all()):
            live_ids.add(context.id)
            if not context.is_running() or context.paused:
                states.pop(context.id, None)
                continue

            marker = _progress_marker(context)
            state = states.get(context.id)
            if state is None:
                states[context.id] = {"marker": marker, "since": now, "nudges": [], "gave_up": False}
                continue
            if marker != state["marker"]:
                state.update(marker=marker, since=now, gave_up=False)
                continue
            if decision_pending:
                state["since"] = now
                continue
            if state["gave_up"] or now - state["since"] < STALL_SECONDS:
                continue

            state["nudges"] = [t for t in state["nudges"] if now - t < NUDGE_WINDOW_SECONDS]
            if len(state["nudges"]) >= MAX_NUDGES_PER_WINDOW:
                state["gave_up"] = True
                self._notify_gave_up(context)
                continue

            if self._nudge(context, len(state["nudges"]) + 1):
                state["nudges"].append(now)
                # The nudge's own log lines move the marker; baseline after
                # them so only the agent's real activity counts as progress.
                state.update(marker=_progress_marker(context), since=now)

        for stale_id in set(states) - live_ids:
            states.pop(stale_id, None)

    def _nudge(self, context, attempt: int) -> bool:
        minutes = STALL_SECONDS // 60
        try:
            context.nudge()
            context.log.log(
                type="warning",
                content=(
                    f"Watchdog: no progress for {minutes} minutes - agent auto-nudged "
                    f"({attempt}/{MAX_NUDGES_PER_WINDOW} in the last "
                    f"{NUDGE_WINDOW_SECONDS // 3600}h)."
                ),
            )
        except Exception as e:
            PrintStyle.error(f"Stall watchdog failed to nudge {context.id}: {e}")
            return False
        PrintStyle(font_color="yellow", padding=False).print(
            f"Stall watchdog: auto-nudged chat {context.id} after {minutes} min without progress"
        )
        return True

    def _notify_gave_up(self, context) -> None:
        try:
            NotificationManager.send_notification(
                type=NotificationType.ERROR,
                priority=NotificationPriority.HIGH,
                title="Agent stuck",
                message=(
                    f"Chat '{context.name or context.id}' keeps stalling: "
                    f"{MAX_NUDGES_PER_WINDOW} automatic nudges in "
                    f"{NUDGE_WINDOW_SECONDS // 3600}h did not keep it moving."
                ),
                detail="The stall watchdog stopped nudging this chat. Check it and nudge or restart it manually.",
                display_time=0,
                group="stall_watchdog",
                id=f"stall_watchdog_{context.id}",
            )
        except Exception as e:
            PrintStyle.error(f"Stall watchdog notification failed for {context.id}: {e}")
