from agent import AgentContext
from helpers.api import ApiHandler, Request, Response
from plugins._personality.helpers import config as personality_config


class PersonalityList(ApiHandler):
    """List all personalities, plus the active one for a chat if given."""

    async def process(self, input: dict, request: Request) -> dict | Response:
        context_id = str(input.get("context_id", "") or "").strip()

        active_id = personality_config.DEFAULT_ID
        if context_id:
            context = AgentContext.get(context_id)
            if context:
                active_id = str(context.data.get("personality") or personality_config.DEFAULT_ID)

        return {
            "ok": True,
            "personalities": personality_config.get_personalities(),
            "active": active_id,
        }
