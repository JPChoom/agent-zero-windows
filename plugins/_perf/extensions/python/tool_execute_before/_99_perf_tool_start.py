import time

from helpers.extension import Extension

DATA_KEY = "_perf_tool_started"


class PerfToolStart(Extension):
    """Last before-hook, so the measured time is the tool itself."""

    async def execute(self, **kwargs):
        if self.agent:
            self.agent.set_data(DATA_KEY, time.monotonic())
