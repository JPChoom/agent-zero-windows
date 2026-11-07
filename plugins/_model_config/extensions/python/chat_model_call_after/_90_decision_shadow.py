"""Decision model in shadow mode: log what the step really did."""

from helpers.extension import Extension
from plugins._model_config.helpers import decision_shadow


class DecisionShadowOutcome(Extension):
    async def execute(self, call_data: dict | None = None, response=None, reasoning=None, **kwargs):
        if not self.agent or not call_data or call_data.get("background"):
            return
        try:
            if decision_shadow.enabled(self.agent):
                decision_shadow.finish_thinking(self.agent, response, reasoning)
        except Exception:
            pass  # shadow only
