from typing import Any
from agent import AgentContextType
from helpers.extension import Extension
from helpers import files, persist_chat
import os, re, uuid

LEN_MIN = 500

class SaveToolCallFile(Extension):
    def execute(self, data: dict[str, Any] | None = None, **kwargs):
        if not self.agent:
            return

        if self.agent.context.type == AgentContextType.BACKGROUND:
            return
            
        if not data:
            return

        # get tool call result
        result = data.get("tool_result") if isinstance(data, dict) else None
        if result is None:
            return

        # skip short results
        if len(str(result)) < LEN_MIN:
            return

        # message files directory
        msgs_folder = persist_chat.get_chat_msg_files_folder(self.agent.context.id)
        os.makedirs(msgs_folder, exist_ok=True)

        # A unique filename needs no directory scan to pick, unlike counting
        # existing files - that scan used to cost O(n) on every large tool
        # result, turning into O(n^2) work over a long chat's lifetime, and
        # it also has no real reader depending on sequential numbering
        # (nothing indexes these files by number; the whole folder is
        # deleted as a unit by persist_chat.remove_msg_files).
        new_file = files.get_abs_path(msgs_folder, f"{uuid.uuid4().hex}.txt")
        files.write_file(
            new_file,
            result,
        )

        # add the path to the history
        data["file"] = new_file
