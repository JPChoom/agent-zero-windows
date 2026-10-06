from agent import LoopData
from helpers.extension import Extension, best_effort
from plugins._discord_integration.helpers import constants as C


class DiscordContextPrompt(Extension):

    @best_effort("Discord context prompt")
    async def execute(self, system_prompt: list[str] = [], loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent or not self.agent.context.data.get(C.CTX_BOT):
            return
        system_prompt.append(self.agent.read_prompt("fw.discord.system_context_reply.md"))
        instructions = (self.agent.context.data.get(C.CTX_BOT_CFG) or {}).get("agent_instructions", "")
        if instructions:
            system_prompt.append(f"# Discord custom rules\n{instructions}")
