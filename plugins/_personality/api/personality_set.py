from agent import AgentContext
from helpers.api import ApiHandler, Request, Response
from helpers.persist_chat import save_tmp_chat
from helpers.state_monitor_integration import mark_dirty_for_context
from plugins._personality.helpers import config as personality_config


class PersonalitySet(ApiHandler):
    """Set the active personality for one chat."""

    async def process(self, input: dict, request: Request) -> dict | Response:
        context_id = str(input.get("context_id", "") or "").strip()
        personality_id = str(input.get("personality_id", "") or "").strip()

        if not context_id:
            return Response(status=400, response="Missing context_id")
        if not personality_id:
            return Response(status=400, response="Missing personality_id")

        context = AgentContext.get(context_id)
        if not context:
            return Response(status=404, response="Context not found")

        personality = personality_config.get_personality(personality_id)
        if not personality:
            return Response(status=404, response=f"Personality '{personality_id}' not found")

        context.data["personality"] = personality_id
        save_tmp_chat(context)
        mark_dirty_for_context(context.id, reason="personality_change")

        return {"ok": True, "personality_id": personality_id, "name": personality["name"]}
