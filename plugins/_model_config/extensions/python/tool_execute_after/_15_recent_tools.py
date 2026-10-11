"""Remember the last few tools an agent used (for the experimental dynamic sampling)."""

from helpers.extension import Extension
from plugins._model_config.helpers import dynamic_sampling


class RememberRecentTools(Extension):
    async def execute(self, tool_name: str = "", **kwargs):
        if not self.agent or not tool_name:
            return
        recent = self.agent.get_data(dynamic_sampling.RECENT_TOOLS_KEY) or []
        recent = (list(recent) + [tool_name])[-dynamic_sampling.RECENT_TOOLS:]
        self.agent.set_data(dynamic_sampling.RECENT_TOOLS_KEY, recent)
