from typing import Any

from helpers import plugins
from helpers.extension import Extension
from helpers.print_style import PrintStyle

PLUGIN_NAME = "_slack_integration"


class SlackBotSync(Extension):
    """Keep running Slack bots in line with the plugin config."""

    async def execute(self, **kwargs: Any) -> None:
        bots_cfg = (plugins.get_plugin_config(PLUGIN_NAME) or {}).get("bots", []) or []
        from plugins._slack_integration.helpers import bot

        wanted = [b for b in bots_cfg if b.get("enabled") and b.get("bot_token") and b.get("app_token")]
        if wanted and not bot.has_library():
            PrintStyle.error("Slack: slack-sdk is not installed. Run: pip install -r plugins/_slack_integration/requirements.txt")
            return
        bot.sync(bots_cfg)
