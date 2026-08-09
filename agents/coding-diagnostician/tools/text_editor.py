"""Diagnostician-profile override of text_editor: read-only.

Profile-scoped tool resolution (helpers/subagents.py: get_paths(), called
from agent.py: Agent.get_tool()) searches project -> usr/agents/<profile>/
tools/ -> ... and uses the FIRST match, so this file permanently shadows
plugins/_text_editor/tools/text_editor.py for the coding-diagnostician
profile only. This is real code-level enforcement, not a prompt
convention - the diagnostician investigates why repairs failed, it must
not be able to modify anything itself (same restriction and rationale as
agents/coding-reviewer/tools/text_editor.py, duplicated here rather than
shared since profile-scoped tool resolution has no cross-profile
inheritance mechanism).

Deliberately a standalone class (not a subclass importing the real
TextEditor) to match this repo's own established profile-override pattern
(agents/_example/tools/response.py) and avoid relying on
helpers/modules.py: load_classes_from_file()'s reversed-alphabetical-name
tie-breaking between an imported base class and a local subclass, which
works today but is a fragile thing to depend on.
"""

from helpers.tool import Tool, Response
from helpers import plugins, runtime
from plugins._text_editor.helpers.file_ops import read_file, file_info
from plugins._text_editor.helpers.patch_state import (
    LOCAL_FRESHNESS_KEY,
    record_file_state,
)


class TextEditor(Tool):

    async def execute(self, **kwargs):
        action = (
            str(kwargs.get("action") or self.args.get("action") or "")
            .strip()
            .lower()
            .replace("-", "_")
        )
        if action != "read":
            return Response(
                message=(
                    "The diagnostician role is read-only and cannot write or patch files "
                    f"(action='{action or 'unknown'}' is not permitted here). "
                    "Use action=read to inspect content."
                ),
                break_loop=False,
            )

        path = kwargs.get("path", "")
        if not path:
            return Response(message="path is required", break_loop=False)

        cfg = plugins.get_plugin_config("_text_editor", agent=self.agent) or {}
        raw_to = kwargs.get("line_to")
        result = await runtime.call_development_function(
            read_file,
            path,
            line_from=int(kwargs.get("line_from", 1)),
            line_to=int(raw_to) if raw_to is not None else None,
            max_line_tokens=int(cfg.get("max_line_tokens", 500)),
            default_line_count=int(cfg.get("default_line_count", 100)),
            max_total_read_tokens=int(cfg.get("max_total_read_tokens", 4000)),
        )
        if result["error"]:
            return Response(
                message=f"Error reading '{path}': {result['error']}",
                break_loop=False,
            )

        info = await runtime.call_development_function(file_info, path)
        record_file_state(
            self.agent, info, key=LOCAL_FRESHNESS_KEY, total_lines=result["total_lines"]
        )

        msg = self.agent.read_prompt(
            "fw.text_editor.read_ok.md",
            path=info["expanded"],
            total_lines=str(result["total_lines"]),
            warnings=result["warnings"],
            content=result["content"],
        )
        return Response(message=msg, break_loop=False)
