"""Whether this chat's Telegram bot has a non-empty allowlist, for
helpers/channel_approvals.py: phone approvals only on a closed channel."""

from __future__ import annotations


def channel_allowlist_set(context) -> bool:
    from helpers import plugins
    from plugins._telegram_integration.helpers.constants import CTX_TG_BOT

    name = (getattr(context, "data", None) or {}).get(CTX_TG_BOT)
    bots = (plugins.get_plugin_config("_telegram_integration") or {}).get("bots") or []
    bot = next((b for b in bots if isinstance(b, dict) and b.get("name") == name), None)
    return bool(bot and bot.get("allowed_users"))
