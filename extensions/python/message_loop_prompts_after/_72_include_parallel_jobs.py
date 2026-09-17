from helpers.extension import Extension, best_effort
from agent import LoopData
from helpers import parallel_tools


class IncludeParallelJobs(Extension):
    @best_effort("Parallel jobs")
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        extras = await parallel_tools.build_parallel_jobs_extras(self.agent)
        if extras:
            loop_data.extras_temporary["parallel_jobs"] = extras
