from helpers.extension import Extension
from plugins._model_config.helpers import job_routing


class UtilityModelProvider(Extension):
    def execute(self, data: dict = {}, **kwargs):
        if self.agent:
            data["result"] = job_routing.utility_model_for_call(self.agent)
