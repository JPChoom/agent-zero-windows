from typing import Any

from helpers import plugins
from helpers.extension import Extension
from helpers.print_style import PrintStyle

PLUGIN_NAME = "_discord_integration"


class DiscordBotSync(Extension):
    """Keep running Discord bots in line with the plugin config."""

    async def execute(self, **kwargs: Any) -> None:
        bots_cfg = (plugins.get_plugin_config(PLUGIN_NAME) or {}).get("bots", []) or []
        from plugins._discord_integration.helpers import bot

        wanted = [b for b in bots_cfg if b.get("enabled") and b.get("token")]
        if wanted and not bot.has_library():
            PrintStyle.error("Discord: discord.py is not installed. Run: pip install -r plugins/_discord_integration/requirements.txt")
            return
        bot.sync(bots_cfg)
