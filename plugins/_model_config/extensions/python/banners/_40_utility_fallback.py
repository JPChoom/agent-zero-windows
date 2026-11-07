from helpers.extension import Extension
from plugins._model_config.helpers import job_routing, model_config


class UtilityFallbackBanner(Extension):
    """Say so while Utility jobs are running on the Main model: chats work but
    slower, and the cause (a PC asleep) is the user's to fix."""

    async def execute(self, banners: list = [], frontend_context: dict = {}, **kwargs):
        try:
            api_base = model_config.get_utility_model_config().get("api_base")
            if not job_routing.is_marked_down(api_base):
                return
        except Exception:
            return  # advisory only
        banners.append(
            {
                "id": "utility-fallback",
                "type": "warning",
                "priority": 70,
                "title": "Utility model not answering",
                "html": "Background jobs are running on the Main model until it answers again, so replies may be slower.",
                "dismissible": True,
                "source": "backend",
            }
        )
