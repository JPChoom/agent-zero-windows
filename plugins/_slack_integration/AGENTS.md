# Slack Integration Plugin DOX

## Purpose

- Own talking to Agent Zero through a Slack app over Socket Mode: DMs and channel @mentions answered in threads, one chat per (app, user, channel, thread).

## Ownership

- `helpers/bot.py` owns the slack_sdk Socket Mode client per app (thread loop via `helpers/chat_channels.BotThread`), event filtering (`classify_event`), Markdown-to-mrkdwn (`to_mrkdwn`), downloads, the working reaction, replies, and the token test.
- `helpers/constants.py` owns context-data keys and limits.
- Extensions mirror the Discord plugin: `job_loop/_10_slack_bot.py`, `process_chain_end/_55_slack_reply.py`, `tool_execute_after/_50_slack_response.py`, `system_prompt/_20_slack_context.py`.
- `api/test_connection.py`, `webui/config.html`, `prompts/`, `default_config.yaml`, `requirements.txt` own token test, settings UI, prompts, defaults, and the pinned `slack-sdk`.

## Local Contracts

- Needs both a bot token (xoxb-) and an app-level token (xapp-, connections:write); no public URL or webhook.
- `allowed_users` empty = nobody; ignored member ids are logged. Bot messages, edits and the app's own messages are ignored.
- DMs (`message.im`) are always considered; channels follow `channel_mode` (mention via `app_mention` | all via `message.channels` | off) and optional `allowed_channels`. A mention that also arrives as a channel message is answered once.
- New chats carry `slack_channel_id` (`CTX_CHANNEL`), the `_permissions` channel marker (cap `channel_mode_caps.slack`, default manual).
- Channel conversations reply in the thread; the :eyes: reaction marks work in progress (best effort).
- Never auto-install dependencies at runtime.

## Verification

- `pytest tests/test_chat_integrations.py`
- Token test: Settings > External > Slack > Test tokens.

## Child DOX Index

No child DOX files.
