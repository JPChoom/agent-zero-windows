from helpers.api import ApiHandler, Input, Output, Request
from plugins._model_config.helpers import model_config


class ContextUsageGet(ApiHandler):
    async def process(self, input: Input, request: Request) -> Output:
        ctxid = input.get("context", "")
        if not ctxid:
            return {"ok": False, "error": "context is required"}

        try:
            context = self.use_context(ctxid, create_if_not_exists=False)
        except Exception:
            context = None
        if context is None:
            return {"ok": False, "error": "context not found"}

        agent = context.streaming_agent or context.agent0
        window = agent.get_data(agent.DATA_NAME_CTX_WINDOW)
        tokens = 0
        if isinstance(window, dict):
            tokens = int(window.get("tokens") or 0)

        chat_cfg = model_config.get_chat_model_config(agent)
        max_tokens = int(chat_cfg.get("ctx_length") or 0)

        percent = round((tokens / max_tokens) * 100, 1) if max_tokens > 0 else None

        return {
            "ok": True,
            "tokens": tokens,
            "max_tokens": max_tokens,
            "percent": percent,
        }
