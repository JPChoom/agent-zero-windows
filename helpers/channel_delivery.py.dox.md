# channel_delivery.py DOX

## Purpose

- Own reliable delivery of agent replies to messaging channels: in-line retries, a persistent retry queue, and one place that tells a temporary failure from a permanent one.

## Ownership

- Public: `deliver(context, text, attachments, send=, queue=, delays=, sleep=)` -> `Delivery(ok, error, kind, queued, attempts)`, `drain(now=, send=)`, `classify(error)`, `retry_after(error)`, `enqueue(...)`, `pending()`, `sender_for(channel)`.
- Constants: `RETRY_DELAYS` (2, 6, 20 s), `RETRY_AFTER_CAP`, `QUEUE_DELAYS`, `QUEUE_MAX_AGE` (24 h), `QUEUE_MAX_ATTEMPTS`, `QUEUE_MAX_ENTRIES`, `OUTBOX_FILE` (`usr/channel_outbox.json`, git-ignored).

## Runtime Contracts

- Every reply send of every integration goes through `deliver` (tests/test_channel_delivery.py checks each site): final replies use the queue, mid-task updates, error notices and approval questions use `queue=False` (a stale one is worthless).
- `send(context, text, attachments)` returns "" / None on success or an error string; an exception counts as an error. Integrations must report failure that way - a send function that swallows its error makes the reply look delivered (Telegram's `send_text` did; `raise_errors=True` fixes it for replies).
- `classify`: "permanent" (blocked bot, chat or channel gone, bad credentials, 4xx other than 429, 535/55x) is returned to the caller at once and never queued; everything else, unknown errors included, is "transient" and bounded by attempts and age. Callers keep their own handling of a permanent failure (the Telegram/WhatsApp/email extensions still tell the agent, up to twice).
- A reply still failing after the in-line retries is queued and the chat gets a warning; `drain` (job loop `_35_channel_outbox.py`, once a minute) retries due entries with growing gaps and drops one that is permanent, `QUEUE_MAX_AGE` old, past `QUEUE_MAX_ATTEMPTS`, for a deleted chat, or for a channel with no sender. A delivered or dropped entry is noted in its chat.
- At-least-once: a send whose confirmation was lost can arrive twice. A queued reply is replayed as text plus the attachments that still exist; a Telegram keyboard is not kept.
- The queue file is replaced atomically; an unreadable one is renamed `.bad` and a new queue started. Entries queued while a drain runs are kept.

## Verification

- `pytest tests/test_channel_delivery.py tests/test_channel_approvals.py`.
