"""Decision model in shadow mode: judge a delegated task as it starts."""

from helpers.extension import Extension
from plugins._model_config.helpers import decision_shadow


class SubordinateShadow(Extension):
    async def execute(self, tool_args: dict | None = None, tool_name: str = "", **kwargs):
        if not self.agent or tool_name != "call_subordinate":
            return
        try:
            if decision_shadow.enabled(self.agent):
                decision_shadow.start_subordinate(self.agent, tool_args)
        except Exception:
            pass  # shadow only
