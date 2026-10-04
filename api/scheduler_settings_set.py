from helpers.api import ApiHandler, Input, Output, Request
from helpers.task_scheduler import SchedulerSettings, save_scheduler_settings


class SchedulerSettingsSet(ApiHandler):
    async def process(self, input: Input, request: Request) -> Output:
        catch_up = input.get("catch_up_missed_runs")
        if not isinstance(catch_up, bool):
            return {"ok": False, "error": "catch_up_missed_runs must be a boolean"}

        settings = save_scheduler_settings(SchedulerSettings(catch_up_missed_runs=catch_up))
        return {"ok": True, "settings": settings.model_dump()}
