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


def _read_tool_prompt(agent: Agent, prompt_dirs: list[str], basename: str, extra: dict) -> str:
    """agent.read_prompt with the prompt folders computed once per build.

    agent.read_prompt looks the folders up again for every file (plugin
    discovery, thousands of path checks); for ~30 tool files that was most of
    the build time on every turn.
    """
    prompt = files.read_prompt_file(basename, _directories=prompt_dirs, _agent=agent, **extra)
    if files.is_full_json_template(prompt):
        prompt = files.remove_code_fences(prompt)
    return prompt


def _declared_tool_name(basename: str, prompt: str) -> str:
    """The tool name a prompt declares (code_exe.md describes code_execution_tool)."""
    fallback = basename[len("agent.system.tool."):-len(".md")]
    try:
        from helpers.responses_tools import _tool_name_from_prompt

        return _tool_name_from_prompt(prompt, fallback=fallback)
    except Exception:
        return fallback


@extensible
async def build_prompt(agent: Agent) -> str:
    # collect tool files from all prompt directories
    prompt_dirs = subagents.get_paths(agent, "prompts")
    tool_files = files.get_unique_filenames_in_dirs(
        prompt_dirs, "agent.system.tool.*.md"
    )

    # per-file kwargs registered by plugin config extensions (e.g. _09_text_editor_config)
    all_tool_kwargs: dict[str, dict[str, Any]] = agent.get_data(TOOL_KWARGS_KEY) or {}

    try:
        from plugins._capabilities.helpers import policy as capability_policy
    except Exception:
        capability_policy = None

    tools: list[str] = []
    for tool_file in tool_files:
        try:
            basename = os.path.basename(tool_file)
            extra = all_tool_kwargs.get(basename, {})
            tool = _read_tool_prompt(agent, prompt_dirs, basename, extra)
            if capability_policy and capability_policy.tool_hidden(agent, _declared_tool_name(basename, tool)):
                continue  # outside this agent's capabilities: not offered
            tools.append(tool)
        except Exception as e:
            PrintStyle().error(f"Error loading tool '{tool_file}': {e}")

    if capability_policy:
        limits = capability_policy.restrictions(agent)
        if limits:
            tools.append("## Capability limits\nThis agent may not use these tools or actions, in any mode: "
                         + "; ".join(limits) + ". Do the task without them, or tell the user it needs a different agent.")
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
