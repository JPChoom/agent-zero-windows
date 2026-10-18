from helpers import perf
from helpers.extension import Extension


class PerfTurnStart(Extension):
    """Open a timing record for the top-level agent's turn.

    Sub-agents run inside their superior's turn on the same chat, so their
    model calls and tools are charged to it; only agent 0 opens and closes.
    """

    async def execute(self, **kwargs):
        if not self.agent or getattr(self.agent, "number", 0) != 0:
            return
        perf.turn_start(str(self.agent.context.id), self.agent.agent_name)
