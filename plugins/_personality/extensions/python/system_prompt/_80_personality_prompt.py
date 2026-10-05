from helpers.extension import Extension, best_effort
from agent import LoopData

from plugins._personality.helpers import config as personality_config


class PersonalityPrompt(Extension):
    """Appends the chat's active personality prompt (if any) to the system
    prompt. Runs late (_80) so it lands near the end of the prompt list,
    after the main prompt and behaviour rules - a personality is meant to
    be a tone/stance overlay on top of those, not compete with them."""

    @best_effort("Personality prompt")
    async def execute(self, system_prompt: list[str] = [], loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        personality_id = self.agent.context.data.get("personality")
        if not personality_id or personality_id == personality_config.DEFAULT_ID:
            return

        personality = personality_config.get_personality(personality_id)
        if not personality or not personality.get("prompt"):
            return

        system_prompt.append(personality["prompt"])
