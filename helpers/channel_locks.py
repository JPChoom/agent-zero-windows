"""What a messaging channel's settings pin for its chats, resolved from the live settings.

A channel can pin an agent profile (`agent_profile`) and a project
(`default_project` / `project`, or one per user in `user_projects`). The
profile's and project's own capability limits then apply to the chat. The
chat commands `/agent` and `/project` would swap them for another and so
leave those limits; `pinned` tells them to refuse. The channel's
`allow_switching` setting turns the lock off. Global capability limits and
`messaging_deny` bind every profile and project and are not affected.
"""

from __future__ import annotations

from helpers import channels, plugins

_PLUGINS = {
    "telegram": ("_telegram_integration", "bots", "telegram_bot", "telegram_user_id", "default_project"),
    "discord": ("_discord_integration", "bots", "discord_bot", "discord_user_id", "default_project"),
    "slack": ("_slack_integration", "bots", "slack_bot", "slack_user_id", "default_project"),
    "email": ("_email_integration", "handlers", "email_handler", "", "project"),
    "whatsapp": ("_whatsapp_integration", "", "", "", "project"),
}


def channel_config(context) -> tuple[dict, str]:
    """The live settings of the bot or account this chat came in on, and the
    chat's user key. ({}, "") for a chat that is not a channel chat or whose
    bot or account no longer exists."""
    channel = channels.channel_of(context)
    spec = _PLUGINS.get(channel)
    data = getattr(context, "data", None)
    if not spec or not isinstance(data, dict):
        return {}, ""
    plugin, list_key, name_key, user_key, _project_key = spec
    try:
        cfg = plugins.get_plugin_config(plugin) or {}
    except Exception:
        return {}, ""
    user = str(data.get(user_key) or "") if user_key else ""
    if not list_key:
        return (cfg if isinstance(cfg, dict) else {}), user
    wanted = data.get(name_key)
    for item in cfg.get(list_key) or []:
        if isinstance(item, dict) and item.get("name") == wanted:
            return item, user
    return {}, user


def pinned(context) -> dict[str, bool]:
    """{"profile": bool, "project": bool}: which of the chat's agent profile
    and project its channel's settings pin (and `/agent`, `/project` must not change)."""
    cfg, user = channel_config(context)
    if not cfg or cfg.get("allow_switching"):
        return {"profile": False, "project": False}
    spec = _PLUGINS.get(channels.channel_of(context))
    project_key = spec[4] if spec else "project"
    per_user = cfg.get("user_projects") if isinstance(cfg.get("user_projects"), dict) else {}
    return {
        "profile": bool(str(cfg.get("agent_profile") or "").strip()),
        "project": bool(str(cfg.get(project_key) or "").strip() or (user and str(per_user.get(user) or "").strip())),
    }
