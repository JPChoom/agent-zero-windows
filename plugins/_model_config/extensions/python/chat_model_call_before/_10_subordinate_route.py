"""A subordinate that works on the Utility model goes back to the Main model
when that server does not answer (helpers/job_routing.py).

Before the sampling and thinking hooks, so they adjust the model that runs.
"""

from helpers.extension import Extension
from plugins._model_config.helpers import job_routing, model_config


class SubordinateRoute(Extension):
    async def execute(self, call_data: dict | None = None, **kwargs):
        if not self.agent or not call_data or not model_config.subordinate_on_utility(self.agent):
            return
        if not job_routing.settings(self.agent).get("fallback_to_main", True):
            return
        api_base = model_config.get_utility_model_config(self.agent).get("api_base")
        if not await job_routing.available(api_base):
            call_data["model"] = model_config.build_chat_model(self.agent, routed=False)
