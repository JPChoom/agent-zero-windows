# chat_channels.py DOX

## Purpose

- Own the plumbing shared by chat-app integrations (`plugins/_discord_integration`, `plugins/_slack_integration`): sender allowlist, conversation-to-chat mapping, message delivery/queueing, reply lookup, text splitting, attachment paths, and the per-client thread loop with restart backoff.

## Ownership

- `chat_channels.py` owns the runtime implementation; this file owns its contracts.
- Public API: `is_allowed`, `ChannelState`, `get_or_create_context`, `deliver`, `last_response`, `split_text`, `download_path`, `BotThread`, `RUNNING`, `sync_clients`, `restart_allowed`, `mark_healthy`.

## Runtime Contracts

- `is_allowed`: an empty allowlist allows nobody. Matches ids and (case-insensitive, `@` optional) names.
- `ChannelState(plugin)` persists `usr/plugins/<plugin>/state.json` (`chats`: key -> context id), written atomically.
- `get_or_create_context` stamps the integration's context data on new chats (including the `_permissions` channel marker key) and refreshes non-underscore keys on reuse; stale ids are dropped.
- `deliver` queues through `helpers/message_queue` while a run is active and returns the notice to send back; otherwise logs and starts the run.
- `BotThread` runs a client's coroutine in its own daemon thread and loop; `run()` awaits work on that loop from any other loop. `ended_at` is set when the thread finishes.
- `RUNNING` lives here (not in a plugin) because plugin modules are re-imported on plugin file changes; keys are `<integration>:<bot name>`.
- `sync_clients` restarts a client immediately when its connection fingerprint changes, and after a backoff (30 s doubling to 30 min) when it died with unchanged settings; `mark_healthy` resets the backoff after a successful connection.
- Attachments go to `usr/uploads/<prefix>_<random>_<sanitized name>`.

## Verification

- `pytest tests/test_chat_integrations.py`
