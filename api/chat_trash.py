from helpers.api import ApiHandler, Input, Output, Request, Response
from helpers import chat_trash


class ChatTrash(ApiHandler):
    """Recently deleted chats: list, restore, delete forever, empty."""

    async def process(self, input: Input, request: Request) -> Output:
        action = str(input.get("action", "list"))
        try:
            if action == "list":
                return {
                    "items": chat_trash.list_trash(),
                    "retention_days": chat_trash.RETENTION_DAYS,
                }

            if action == "restore":
                ctxid = chat_trash.restore_chat(str(input.get("trash_id", "")))
                _mark_lists_dirty()
                return {"ok": True, "context_id": ctxid}

            if action == "delete":
                chat_trash.purge(str(input.get("trash_id", "")))
                return {"ok": True}

            if action == "empty":
                return {"ok": True, "deleted": chat_trash.empty_trash()}
        except chat_trash.TrashError as exc:
            return Response(response=str(exc), status=400, mimetype="text/plain")

        return Response(response="Unknown action.", status=400, mimetype="text/plain")


def _mark_lists_dirty() -> None:
    # A restored chat appears in the chat list of every open tab.
    from helpers.state_monitor_integration import mark_dirty_all

    mark_dirty_all(reason="api.chat_trash.restore")
