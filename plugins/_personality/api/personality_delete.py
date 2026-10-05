from helpers.api import ApiHandler, Request, Response
from plugins._personality.helpers import config as personality_config


class PersonalityDelete(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        personality_id = str(input.get("id", "") or "").strip()
        if not personality_id:
            return {"ok": False, "error": "id is required"}

        try:
            personality_config.delete_personality(personality_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": True}
