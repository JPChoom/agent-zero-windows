PLUGIN_NAME = "_discord_integration"
SOURCE = "discord"

# Context data keys. CTX_CHANNEL is also _permissions' channel marker
# (helpers/config.py CHANNEL_MARKERS) - keep the name in sync.
CTX_BOT = "discord_bot"
CTX_BOT_CFG = "discord_bot_cfg"
CTX_CHANNEL = "discord_channel_id"
CTX_USER = "discord_user_id"
CTX_REPLY_TO = "_discord_reply_to"
CTX_ATTACHMENTS = "_discord_response_attachments"
CTX_TYPING = "_discord_typing_stop"

MESSAGE_LIMIT = 2000          # Discord's hard limit per message
ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
