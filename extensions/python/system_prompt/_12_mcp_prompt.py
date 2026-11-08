from typing import Any

from helpers.extension import Extension, extensible, best_effort
from helpers.mcp_handler import MCPConfig
from agent import Agent, LoopData


class MCPToolsPrompt(Extension):

    @best_effort("MCP tools prompt")
    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        prompt = await build_prompt(self.agent)
        if prompt:
            system_prompt.append(prompt)


@extensible
async def build_prompt(agent: Agent) -> str:
    mcp_config = MCPConfig.get_for_agent(agent)
    if not mcp_config.servers:
        return ""

    pre_progress = agent.context.log.progress
    agent.context.log.set_progress("Collecting MCP tools")
    try:
        from plugins._capabilities.helpers import policy

        tools = mcp_config.get_tools_prompt(include=lambda name: not policy.tool_hidden(agent, name))
    except ImportError:
        tools = mcp_config.get_tools_prompt()
    agent.context.log.set_progress(pre_progress)
    return tools
