"""API handler for chat compaction."""
from helpers.api import ApiHandler, Input, Output, Request, Response
from agent import AgentContext
from plugins._chat_compaction.helpers.compactor import (
    MIN_COMPACTION_TOKENS,
    get_compaction_stats,
    run_compaction,
)


class CompactChat(ApiHandler):
    """Compact the current chat history into a summarized message."""

    async def process(self, input: Input, request: Request) -> Output:
        ctxid = input.get("context", "")
        action = input.get("action", "compact")

        if not ctxid:
            return Response("Missing context id", 400)

        context = AgentContext.get(ctxid)
        if not context:
            return Response("Context not found", 404)

        if context.is_running():
            return Response("Cannot compact while agent is running", 409)

        visible_count = len(context.log.logs)
        if visible_count <= 1:
            return Response("Not enough messages to compact", 400)

        # Gate both stats and compact — no point opening the modal for tiny chats
        stats = await get_compaction_stats(context)
        if stats["token_count"] < MIN_COMPACTION_TOKENS:
            return {
                "ok": False,
                "message": f"Not enough content to compact (minimum {MIN_COMPACTION_TOKENS:,} tokens)",
            }

        if action == "stats":
            return {"ok": True, "stats": stats}

        elif action == "compact":
            use_chat_model = input.get("use_chat_model", True)
            preset_name = input.get("preset_name") or None

            context.run_task(
                _run_compaction_task, context, use_chat_model, preset_name
            )

            return {"ok": True, "message": "Compaction started"}

        else:
            return Response(f"Unknown action: {action}", 400)


async def _run_compaction_task(context, use_chat_model: bool, preset_name: str | None):
    """Wrapper to run compaction and handle errors."""
    try:
        await run_compaction(context, use_chat_model, preset_name)
    except Exception as e:
        context.log.log(
            type="error",
            heading="Compaction Failed",
            content=str(e),
        )
        from helpers.state_monitor_integration import mark_dirty_all
        mark_dirty_all(reason="plugins._chat_compaction.compact_chat_error")
