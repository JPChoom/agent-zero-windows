"""Thinking budget: turn the Main model's thinking off for this call when
Settings > Agent > Models > Thinking says so (helpers/thinking.py).

Each call builds a fresh model object, so the change affects this call only.
"""

from helpers.extension import Extension
from plugins._model_config.helpers import model_config, thinking


class ThinkingBudget(Extension):
    async def execute(self, call_data: dict | None = None, **kwargs):
        if not self.agent or not call_data:
            return
        mode = thinking.mode(model_config.get_config(self.agent))
        if mode == "on":
            return
        model = call_data.get("model")
        if model is None:
            return
        loop_data = getattr(self.agent, "loop_data", None)
        iteration = int(getattr(loop_data, "iteration", 0) or 0)
        think = thinking.should_think(mode, iteration, thinking.last_message_text(self.agent))
        provider = str(getattr(getattr(model, "a0_model_conf", None), "provider", "") or getattr(model, "provider", "") or "")
        applied = False if think else thinking.apply(model, provider)
        self.agent.set_data(thinking.LAST_DECISION_KEY, {"mode": mode, "iteration": iteration,
                                                         "think": think or not applied})
