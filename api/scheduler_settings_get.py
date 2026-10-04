from helpers.api import ApiHandler, Input, Output, Request
from helpers.task_scheduler import get_scheduler_settings


class SchedulerSettingsGet(ApiHandler):
    async def process(self, input: Input, request: Request) -> Output:
        settings = get_scheduler_settings()
        return {"ok": True, "settings": settings.model_dump()}
