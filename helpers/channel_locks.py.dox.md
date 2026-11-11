# channel_locks.py DOX

## Purpose

- Own what a messaging channel's settings pin for its chats, so chat commands cannot undo it.

## Ownership

- Public: `channel_config(context)` -> (the live settings of the bot or account the chat came in on, the chat's user key), `pinned(context)` -> `{"profile": bool, "project": bool}`.

## Runtime Contracts

- Resolved from the live plugin settings on every call (Telegram, Discord and Slack `bots`, email `handlers`, WhatsApp's flat config), never from a snapshot in the chat, so changing the settings applies to existing chats. A chat that is not a channel chat, or whose bot or account was removed, is not locked.
- A channel pins the agent profile with `agent_profile` and the project with `default_project` (`project` for email and WhatsApp) or a `user_projects` entry for the chat's user. The channel's `allow_switching` turns both locks off.
- `helpers/integration_commands` refuses `/agent` and `/project` (switching or clearing; listing stays allowed) when pinned. Global capability limits and `messaging_deny` bind every profile and project and do not depend on this.
- `plugins/_telegram_integration/helpers/session_scope` reads `channel_config` for `allow_webui_sessions`.

## Verification

- `pytest tests/test_channel_admin_boundary.py`.
