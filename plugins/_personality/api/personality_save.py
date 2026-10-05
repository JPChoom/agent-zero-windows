from helpers.api import ApiHandler, Request, Response
from plugins._personality.helpers import config as personality_config


class PersonalitySave(ApiHandler):
    """Create a personality (no id, or an id that doesn't exist yet) or
    update one (id matches an existing entry - builtins included)."""

    async def process(self, input: dict, request: Request) -> dict | Response:
        personality_id = input.get("id")
        personality_id = str(personality_id).strip() if personality_id else None
        name = input.get("name")
        prompt = input.get("prompt", "")

        if not isinstance(name, str) or not name.strip():
            return {"ok": False, "error": "name is required"}
        if not isinstance(prompt, str):
            return {"ok": False, "error": "prompt must be text"}

        try:
            saved = personality_config.save_personality(personality_id, name, prompt)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "personality": saved}
