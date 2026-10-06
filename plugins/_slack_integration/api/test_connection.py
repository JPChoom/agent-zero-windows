from helpers.api import ApiHandler, Request
from helpers.errors import format_error


class TestConnection(ApiHandler):

    async def process(self, input: dict, request: Request) -> dict:
        cfg = input.get("bot") or {}
        bot_token = str(cfg.get("bot_token") or "").strip()
        app_token = str(cfg.get("app_token") or "").strip()
        if not bot_token or not app_token:
            return {"success": False, "message": "Add both the bot token (xoxb-) and the app-level token (xapp-) first."}
        from plugins._slack_integration.helpers import bot

        try:
            ok, message = await bot.test_tokens(bot_token, app_token)
        except Exception as e:
            ok, message = False, f"Could not reach Slack: {format_error(e)}"
        if ok and not (cfg.get("allowed_users") or []):
            message += " Note: allowed users is empty, so the app will not answer anyone yet."
        return {"success": ok, "message": message}
