from datetime import datetime, timedelta, timezone
from typing import Any

from agent import AgentContext
from helpers import persist_chat
from helpers.extension import Extension
from helpers.print_style import PrintStyle
from helpers.state_monitor_integration import mark_dirty_all


CHECK_INTERVAL = timedelta(hours=1)
LIFETIME_KEY = "lifetime_hours"


class CleanupExpiredApiChats(Extension):
    _last_check: datetime | None = None

    async def execute(self, data: dict[str, Any] | None = None, **kwargs):
        now = datetime.now(timezone.utc)
        if type(self)._last_check and now - type(self)._last_check < CHECK_INTERVAL:
            return
        type(self)._last_check = now

        removed = 0
        for context in list(AgentContext.all()):
            lifetime_hours = context.get_data(LIFETIME_KEY)
            if lifetime_hours is None:
                continue

            try:
                lifetime = timedelta(hours=float(lifetime_hours))
            except (TypeError, ValueError):
                PrintStyle.error(
                    f"Invalid chat lifetime for {context.id}: {lifetime_hours}"
                )
                continue

            if lifetime <= timedelta(0) or context.is_running():
                continue

            last_message = _as_utc(context.last_message)
            if now - last_message <= lifetime:
                continue

            try:
                context.reset()
                AgentContext.remove(context.id)
                persist_chat.remove_chat(context.id)
                removed += 1
                PrintStyle().print(f"Cleaned up expired API chat: {context.id}")
            except Exception as e:
                PrintStyle.error(f"Failed to cleanup expired API chat {context.id}: {e}")

        if removed:
            mark_dirty_all(reason="job_loop.CleanupExpiredApiChats")


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.fromtimestamp(0, timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
