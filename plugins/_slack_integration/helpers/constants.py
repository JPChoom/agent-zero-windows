PLUGIN_NAME = "_slack_integration"
SOURCE = "slack"

# Context data keys. CTX_CHANNEL is also _permissions' channel marker
# (helpers/config.py CHANNEL_MARKERS) - keep the name in sync.
CTX_BOT = "slack_bot"
CTX_BOT_CFG = "slack_bot_cfg"
CTX_CHANNEL = "slack_channel_id"
CTX_USER = "slack_user_id"
CTX_THREAD = "_slack_thread_ts"
CTX_MESSAGE_TS = "_slack_message_ts"
CTX_ATTACHMENTS = "_slack_response_attachments"

MESSAGE_LIMIT = 3500          # Slack truncates long messages; stay well under 4000
ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
WORKING_REACTION = "eyes"
