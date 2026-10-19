"""Startup tripwire, part 1: note the autostart locations before a tool runs.

Runs last before the tool (after every gate has let it through) so the
window it covers is the tool itself. Part 2 is
tool_execute_after/_01_startup_tripwire.py; see helpers/startup_watch.py.
"""

import asyncio
import time

from helpers import untrusted_content
from helpers.extension import Extension
from plugins._safety_policy.helpers import startup_watch
from plugins._safety_policy.helpers.config import get_config

DATA_KEY = "_plugin._safety_policy.startup_snapshot"
# Tools that cannot change the system on their own.
SKIP_TOOLS = {"response", "call_subordinate"}


def watches(tool_name: str, tool_args: dict | None) -> bool:
    if not tool_name or tool_name in SKIP_TOOLS:
        return False
    return not untrusted_content.is_read_only_call(tool_name, tool_args)


class StartupTripwireBefore(Extension):
    FAIL_LOUD = True  # an undone autostart entry ends the task; isolating it would hide that

    async def execute(self, tool_name: str = "", tool_args: dict | None = None, **kwargs):
        if not self.agent or not watches(tool_name, tool_args):
            return
        if not get_config(self.agent)["startup_tripwire"]:
            return
        # A tool that raised never reached part 2: check its window now,
        # before a new one starts.
        pending = self.agent.get_data(DATA_KEY)
        if pending:
            from plugins._safety_policy.extensions.python.tool_execute_after._01_startup_tripwire import check

            await check(self.agent, pending)
        snapshot = await asyncio.to_thread(startup_watch.take_snapshot)
        self.agent.set_data(DATA_KEY, {"tool": tool_name, "snapshot": snapshot, "started": time.time()})
