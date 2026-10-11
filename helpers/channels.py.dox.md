# channels.py DOX

## Purpose

- Own which messaging channel a chat belongs to: the channel marker keys integrations set on their chats (`CHANNEL_MARKERS`) and `CHANNEL_ORIGIN_KEY` for work derived from a channel chat that runs in its own context.

## Ownership

- `channels.py` owns the runtime implementation; this file owns its durable notes.
- Public: `CHANNEL_MARKERS`, `CHANNEL_ORIGIN_KEY`, `channel_of_data(data)`, `channel_of(context)`.

## Runtime Contracts

- Integration plugins set their marker key (for example `telegram_chat_id`); keep the names in sync with their `constants.py`. Integrations reply to chats that carry their marker, so derived work must never get a marker key.
- `CHANNEL_ORIGIN_KEY` only places a context under that channel's permission cap (`plugins/_permissions`); it never makes the context a live channel chat. Unknown origin values are ignored.
- Scheduled tasks store the creating or last-changing chat's channel in `BaseTask.channel_origin` (`helpers/task_scheduler.py`), which is written into the task chat's data as `CHANNEL_ORIGIN_KEY` when it runs.
- No imports beyond the standard library.

## Verification

- `pytest tests/test_permission_inheritance.py tests/test_chat_integrations.py`

## Child DOX Index

No child DOX files.
