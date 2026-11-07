from helpers import runaway_guard
from helpers.extension import Extension


class RunawayGuard(Extension):
    def execute(self, stream_data: dict | None = None, **kwargs):
        if self.agent:
            runaway_guard.check(self.agent, stream_data)
