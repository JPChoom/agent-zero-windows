from helpers.api import ApiHandler, Request
from helpers.errors import format_error


class TestConnection(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        bot_cfg = input.get("bot") or {}
        token = str(bot_cfg.get("token") or "").strip()
        if not token:
            return {"success": False, "message": "Add the bot token first."}
        from plugins._discord_integration.helpers import bot

        try:
            ok, message = await bot.test_token(token)
        except Exception as e:
            ok, message = False, f"Could not reach Discord: {format_error(e)}"
        if ok and not (bot_cfg.get("allowed_users") or []):
            message += " Note: allowed users is empty, so the bot will not answer anyone yet."
        return {"success": ok, "message": message}
