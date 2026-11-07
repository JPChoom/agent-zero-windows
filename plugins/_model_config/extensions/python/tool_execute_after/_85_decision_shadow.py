"""Decision model in shadow mode: log how a delegated task really went."""

from helpers.extension import Extension
from plugins._model_config.helpers import decision_shadow


class SubordinateShadowOutcome(Extension):
    async def execute(self, response=None, tool_name: str = "", **kwargs):
        if not self.agent or tool_name != "call_subordinate":
            return
        try:
            if decision_shadow.enabled(self.agent):
                decision_shadow.finish_subordinate(self.agent, response)
        except Exception:
            pass  # shadow only
