from helpers.extension import Extension
from agent import LoopData, AgentContextType
from helpers import persist_chat


class SaveChat(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        # Skip saving BACKGROUND contexts as they should be ephemeral
        if self.agent.context.type == AgentContextType.BACKGROUND:
            return

        # save_tmp_chat_async offloads only the disk write to a thread -
        # this runs on every turn, and the write's cost scales with the
        # chat's total accumulated size, so a long-running chat was
        # blocking the whole server for longer and longer on every message.
        await persist_chat.save_tmp_chat_async(self.agent.context)
