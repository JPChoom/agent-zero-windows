import hmac

from helpers.api import ApiHandler, Request, Response
from helpers.print_style import PrintStyle
from plugins._telegram_integration.helpers.dependencies import ensure_dependencies


class TelegramWebhook(ApiHandler):
    """Receives Telegram webhook updates. No auth/CSRF — Telegram cannot send session cookies."""

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ensure_dependencies()
        from aiogram.types import Update

        from plugins._telegram_integration.helpers.bot_manager import get_bot

        # Identify which bot this update is for
        bot_name = request.args.get("bot", "")
        if not bot_name:
            return Response("Missing ?bot= parameter", 400)

        instance = get_bot(bot_name)
        if not instance:
            return Response(f"Bot not found: {bot_name}", 404)

        # Telegram sends the secret registered with set_webhook (always set:
        # setup_webhook generates one when none is configured). Without an
        # active secret this bot is not in webhook mode, so nothing is accepted.
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not instance.webhook_secret or not hmac.compare_digest(
            secret_header.encode("utf-8"), instance.webhook_secret.encode("utf-8")
        ):
            return Response("Invalid secret token", 403)

        # Parse and feed the update to aiogram
        try:
            update = Update.model_validate(input, context={"bot": instance.bot})
            await instance.dispatcher.feed_update(instance.bot, update)
        except Exception as e:
            PrintStyle.error(f"Telegram webhook ({bot_name}): {e}")
            return Response("Internal error", 500)

        return {"ok": True}
