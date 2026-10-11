"""Which messaging channel a chat belongs to.

Integrations mark their chats with a channel-specific context data key
(CHANNEL_MARKERS). Work derived from a channel chat but running in its own
context - a scheduled task the chat created - carries the channel in
CHANNEL_ORIGIN_KEY instead, so it stays under that channel's permission cap
without being mistaken for a live channel chat (integrations reply to chats
that have their marker key).
"""

from __future__ import annotations

CHANNEL_MARKERS = {
    "telegram": "telegram_chat_id",
    "whatsapp": "wa_chat_id",
    "email": "email_sender",
    "discord": "discord_channel_id",
    "slack": "slack_channel_id",
}

CHANNEL_ORIGIN_KEY = "channel_origin"


def channel_of_data(data) -> str:
    """The channel recorded in a context's data, or "" for the local WebUI/API."""
    if not isinstance(data, dict):
        return ""
    for channel, key in CHANNEL_MARKERS.items():
        if data.get(key):
            return channel
    origin = str(data.get(CHANNEL_ORIGIN_KEY) or "").strip().lower()
    return origin if origin in CHANNEL_MARKERS else ""


def channel_of(context) -> str:
    return channel_of_data(getattr(context, "data", None))
