"""EXPERIMENTAL: adjust this call's sampling from what the agent is doing.

Off unless Settings > Agent > Models > Sampling > Dynamic is on. Each call
builds a fresh model object (get_chat_model), so changing its kwargs here
affects this call only. Locked values are never changed.
"""

from helpers.extension import Extension
from plugins._model_config.helpers import dynamic_sampling, model_config


class DynamicSampling(Extension):
    async def execute(self, call_data: dict | None = None, **kwargs):
        if not self.agent or not call_data:
            return
        sampling = model_config.get_sampling(self.agent)
        if not sampling.get("dynamic"):
            return
        model = call_data.get("model")
        if model is None or not isinstance(getattr(model, "kwargs", None), dict):
            return
        loop_data = getattr(self.agent, "loop_data", None)
        message = getattr(loop_data, "user_message", None)
        user_text = getattr(message, "content", "") if message is not None else ""
        recent = self.agent.get_data(dynamic_sampling.RECENT_TOOLS_KEY) or []
        mode = dynamic_sampling.classify(list(recent), str(user_text), sampling.get("dynamic_rules") or {})
        values = dynamic_sampling.adjusted_values(sampling, mode)
        if not values:
            return
        provider = str(getattr(getattr(model, "a0_model_conf", None), "provider", "") or getattr(model, "provider", "") or "")
        extra = model_config.sampling_kwargs(values, provider)
        body = extra.pop("extra_body", {})
        model.kwargs.update(extra)
        if body:
            existing = model.kwargs.get("extra_body") if isinstance(model.kwargs.get("extra_body"), dict) else {}
            model.kwargs["extra_body"] = {**existing, **body}
        self.agent.set_data("_dynamic_sampling_last", {"mode": mode, **values})
