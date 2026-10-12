import os
from typing import Any

from helpers.extension import Extension, extensible
from helpers import files, subagents
from helpers.print_style import PrintStyle
from agent import Agent, LoopData


TOOL_KWARGS_KEY = "_tool_prompt_kwargs"


class ToolsPrompt(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        prompt = await build_prompt(self.agent)
        system_prompt.append(prompt)


@extensible
async def build_prompt(agent: Agent) -> str:
    # collect tool files from all prompt directories
    prompt_dirs = subagents.get_paths(agent, "prompts")
    tool_files = files.get_unique_filenames_in_dirs(
        prompt_dirs, "agent.system.tool.*.md"
    )

    # per-file kwargs registered by plugin config extensions (e.g. _09_text_editor_config)
    all_tool_kwargs: dict[str, dict[str, Any]] = agent.get_data(TOOL_KWARGS_KEY) or {}

    tools: list[str] = []
    for tool_file in tool_files:
        try:
            basename = os.path.basename(tool_file)
            extra = all_tool_kwargs.get(basename, {})
            tool = agent.read_prompt(basename, **extra)
            tools.append(tool)
        except Exception as e:
            PrintStyle().error(f"Error loading tool '{tool_file}': {e}")

    tools_str = "\n\n".join(tools)
    prompt = agent.read_prompt("agent.system.tools.md", tools=tools_str)

    # vision support: the Main model sees images itself, or a vision sidecar
    # model describes them for it (Settings > Models > Vision Sidecar). The
    # agent must be told about vision_load in both cases - with a sidecar and
    # no Main-model vision it used to be left out, so the agent never called
    # it and the sidecar was never used.
    from plugins._model_config.helpers.model_config import (
        get_chat_model_config,
        is_vision_model_configured,
    )

    chat_cfg = get_chat_model_config(agent)
    main_sees = bool(chat_cfg.get("vision", False))
    sidecar = (not main_sees) and is_vision_model_configured(agent)
    if main_sees or sidecar:
        prompt += "\n\n" + agent.read_prompt("agent.system.tools_vision.md")
    if sidecar:
        prompt += (
            "\n\nYou cannot see images yourself. vision_load sends each image to a vision "
            "sidecar model and returns its text description. Call it for any attached or "
            "found image instead of OCR, shell tools or guessing."
        )

    return prompt
