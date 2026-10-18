import time

from helpers import perf
from helpers.extension import Extension

DATA_KEY = "_perf_tool_started"


class PerfToolEnd(Extension):
    """First after-hook: tool time stops before other after-hooks run."""

    async def execute(self, tool_name="", **kwargs):
        if not self.agent:
            return
        started = self.agent.get_data(DATA_KEY)
        if started is None:
            return
        self.agent.set_data(DATA_KEY, None)
        perf.add_tool_time(str(self.agent.context.id), tool_name, time.monotonic() - started)
