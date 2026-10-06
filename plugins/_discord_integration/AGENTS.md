# Discord Integration Plugin DOX

## Purpose

- Own talking to Agent Zero through a Discord bot: DMs and server @mentions, one chat per (bot, user, channel).

## Ownership

- `helpers/bot.py` owns the discord.py client per bot (thread loop via `helpers/chat_channels.BotThread`), incoming message rules, downloads, typing indicator, replies, and the token test.
- `helpers/constants.py` owns context-data keys and limits.
- `extensions/python/job_loop/_10_discord_bot.py` syncs running bots with config; `process_chain_end/_55_discord_reply.py` sends the final response; `tool_execute_after/_50_discord_response.py` captures attachments and sends `break_loop: false` updates; `system_prompt/_20_discord_context.py` adds the channel prompt.
- `api/test_connection.py`, `webui/config.html`, `prompts/`, `default_config.yaml`, `requirements.txt` own token test, settings UI, prompts, defaults, and the pinned `discord.py`.

## Local Contracts

- `allowed_users` empty = nobody; ignored senders are logged with their id. Other bots and the bot itself are ignored.
- DMs are always considered; servers follow `server_mode` (mention | all | off) and optional `allowed_channels`. Only `all` requests the privileged Message Content intent.
- New chats carry `discord_channel_id` (`CTX_CHANNEL`), the `_permissions` channel marker, so Discord chats are capped at `channel_mode_caps.discord` (default manual).
- Integration slash commands go through `helpers/integration_commands` with `integration="discord"`.
- Replies are split at 2000 characters, never ping anyone (`AllowedMentions.none()`), and attach files up to 25 MB.
- Never auto-install dependencies at runtime; report the missing package instead.

## Verification

- `pytest tests/test_chat_integrations.py`
- Token test: Settings > External > Discord > Test token.

## Child DOX Index

No child DOX files.
