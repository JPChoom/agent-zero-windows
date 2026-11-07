"""Decision model in shadow mode: predict beside the step (helpers/decision_shadow.py).

Starts a background request and returns: the step never waits for it, and
call_data is left as it came.
"""

from helpers.extension import Extension
from plugins._model_config.helpers import decision_shadow


class DecisionShadow(Extension):
    async def execute(self, call_data: dict | None = None, **kwargs):
        if not self.agent or not call_data or call_data.get("background"):
            return
        try:
            if decision_shadow.enabled(self.agent):
                decision_shadow.start_thinking(self.agent)
        except Exception:
            pass  # shadow only
