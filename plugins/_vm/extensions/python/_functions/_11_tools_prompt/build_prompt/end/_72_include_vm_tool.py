"""Describe the `vm` tool to the model only where it can work: VirtualBox is
installed and no capability policy refuses the tool. Other installs do not
pay the prompt space."""

from __future__ import annotations

from typing import Any

from helpers.extension import Extension

PROMPT_FILE = "vm.tool.md"
MARKER = '"tool_name": "vm"'


class IncludeVmTool(Extension):
    def execute(self, data: dict[str, Any] = {}, **kwargs: Any) -> None:
        if self.agent is None or not isinstance(data, dict) or not isinstance(data.get("result"), str):
            return
        if MARKER in data["result"]:
            return
        try:
            from plugins._vm.helpers import vbox

            if not vbox.installed():
                return
            try:
                from plugins._capabilities.helpers import policy

                if policy.tool_hidden(self.agent, "vm"):
                    return
            except Exception:
                pass
            prompt = self.agent.read_prompt(PROMPT_FILE).strip()
        except Exception:
            return
        if prompt:
            data["result"] = f"{data['result'].rstrip()}\n\n{prompt}"
