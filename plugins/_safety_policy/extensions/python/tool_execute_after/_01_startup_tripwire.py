"""Startup tripwire, part 2: undo autostart entries the tool added, then stop.

Compares the autostart locations with the snapshot part 1
(tool_execute_before/_90_startup_tripwire.py) took just before the tool ran.
Anything new is undone (helpers/startup_watch.py), the user is told what and
where the backup is, the refusal is recorded for the infection check's
workaround rule, and the task ends: an agent that just slipped past the
command policy should not get another turn to try again.
"""

import asyncio

from helpers.errors import HandledException
from helpers.extension import Extension
from helpers.print_style import PrintStyle
from plugins._safety_policy.helpers import audit_log, denials, startup_watch

DATA_KEY = "_plugin._safety_policy.startup_snapshot"


async def check(agent, pending: dict) -> None:
    """Compare against `pending`'s snapshot; undo and stop on any change."""
    agent.set_data(DATA_KEY, None)
    before = pending.get("snapshot")
    if before is None:
        return
    after = await asyncio.to_thread(startup_watch.take_snapshot)
    changes = startup_watch.compare(before, after)
    if not changes:
        return
    folder = await asyncio.to_thread(startup_watch.undo, changes, before)
    tool = str(pending.get("tool") or "a tool")
    summary = startup_watch.describe(changes)

    context = getattr(agent, "context", None)
    audit_log.append_denial(
        {
            "context_id": str(getattr(context, "id", "") or ""),
            "agent_name": getattr(agent, "agent_name", ""),
            "category": "persistence",
            "pattern": "startup_tripwire",
            "matched_text": "; ".join(change.target for change in changes)[:300],
            "command": tool,
            "outcome": "undone",
            "quarantine": folder,
        }
    )
    denials.record(agent, "persistence", "startup tripwire", f"{tool} added: " + "; ".join(change.target for change in changes))

    user_message = (
        f"[safety_policy] Stopped: {tool} added a program to Windows startup, which the safety "
        f"policy does not allow. It was undone:\n{summary}"
        + (f"\nA copy of what was removed is in {folder}." if folder else "")
    )
    PrintStyle(font_color="red", padding=True).print(user_message)
    try:
        context.log.log(type="warning", heading="Safety policy: startup change undone", content=user_message)
    except Exception:
        pass
    try:
        agent.history.add_message(
            ai=False,
            content=(
                user_message
                + "\nThe task has been stopped. Do not try to add autostart entries again in this chat."
            ),
        )
    except Exception:
        pass
    try:
        from helpers.notification import NotificationManager, NotificationPriority, NotificationType

        NotificationManager.send_notification(
            type=NotificationType.ERROR,
            priority=NotificationPriority.HIGH,
            title="Safety policy",
            message="An agent added a program to Windows startup. It was undone and the task stopped.",
            detail=summary,
            display_time=10,
        )
    except Exception:
        pass
    raise HandledException(Exception("Startup tripwire: autostart change undone"))


class StartupTripwireAfter(Extension):
    FAIL_LOUD = True  # its stop is a raised exception; isolating it would let the task continue

    async def execute(self, tool_name: str = "", **kwargs):
        if not self.agent:
            return
        pending = self.agent.get_data(DATA_KEY)
        if not pending:
            return
        await check(self.agent, pending)
