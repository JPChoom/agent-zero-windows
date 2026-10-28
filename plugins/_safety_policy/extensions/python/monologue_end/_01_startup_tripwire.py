"""Startup tripwire, part 3: check once more when the turn ends.

A tool that raised never reaches tool_execute_after, so an autostart entry it
added before failing was only found at the *next* tool call - which may be a
whole turn away, or never. monologue_end runs after errors too. The turn is
over by now, so this undoes and reports without raising; parts 1 and 2 are
tool_execute_before/_90_startup_tripwire.py and
tool_execute_after/_01_startup_tripwire.py (see helpers/startup_watch.py).
"""

from helpers import extension as _extension  # noqa: F401  (keeps the import order of the sibling hooks)
from helpers.extension import Extension
from plugins._safety_policy.extensions.python.tool_execute_after._01_startup_tripwire import DATA_KEY, check


class StartupTripwireTurnEnd(Extension):
    async def execute(self, **kwargs):
        if not self.agent:
            return
        pending = self.agent.get_data(DATA_KEY)
        if not pending:
            return
        await check(self.agent, pending, stop=False)
