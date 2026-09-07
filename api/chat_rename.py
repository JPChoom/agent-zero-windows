from agent import AgentContext
from helpers import persist_chat
from helpers.api import ApiHandler, Input, Output, Request


# Matches the cap the automatic renamer applies in
# extensions/python/monologue_start/_60_rename_chat.py, so a manual name
# cannot end up wider in the sidebar than a generated one.
MAX_NAME_LENGTH = 40


class RenameChat(ApiHandler):
    """Set a chat's display name.

    Chats are already named automatically after the first exchange; this is
    the manual override. The generated name is not otherwise replaceable,
    and it is derived from an opening message that often does not describe
    where the conversation ended up.
    """

    async def process(self, input: Input, request: Request) -> Output:
        ctxid = str(input.get("context", "") or "")
        name = input.get("name")

        if not ctxid:
            return {"ok": False, "error": "context is required"}
        if not isinstance(name, str):
            return {"ok": False, "error": "name is required"}

        # Collapse whitespace so a pasted multi-line name cannot break the
        # sidebar layout, then bound the length.
        name = " ".join(name.split())
        if not name:
            return {"ok": False, "error": "name cannot be empty"}
        if len(name) > MAX_NAME_LENGTH:
            name = name[:MAX_NAME_LENGTH] + "..."

        context = AgentContext.get(ctxid)
        if not context:
            return {"ok": False, "error": f"no chat with id {ctxid}"}

        context.name = name
        persist_chat.save_tmp_chat(context)

        # The name appears in the chat list, which every tab renders.
        from helpers.state_monitor_integration import mark_dirty_all

        mark_dirty_all(reason="api.chat_rename.RenameChat")

        return {"ok": True, "name": name}
