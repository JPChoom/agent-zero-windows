# Email Integration Plugin DOX

## Purpose

- Own communicating with Agent Zero through email inboxes and SMTP replies.

## Ownership

- `helpers/handler.py` owns mailbox polling, state, dispatch, routing, and reply flow. Its poll tasks and state-file lock live in `helpers.chat_channels.registry("email")`, never in plugin module globals: plugin modules are re-imported when bundled plugin files change, and lost state starts a second poll loop per mailbox.
- `helpers/imap_client.py` and `helpers/smtp_client.py` own inbound and outbound mail transports.
- `helpers/dispatcher.py`, `prompts/`, and attachment helpers own routing decisions and message formatting.
- `api/`, `default_config.yaml`, `plugin.yaml`, `extensions/`, and `webui/` own tests, settings, metadata, hooks, and config UI.

## Local Contracts

- `require_dkim` (per account, default off) answers only mail whose topmost `Authentication-Results` header shows `dmarc=pass` or an aligned `dkim=pass` (`imap_client.sender_authenticated`); Exchange mail is never verified, so it is refused when set.
- Replies are sent through `helpers/channel_delivery.deliver` (in-line retries, then a persistent retry queue); a send function must return its error instead of swallowing it.
- An empty `sender_whitelist` answers nobody (one rule for every channel, owner decision 2026-11-08). Email never answers approval questions: a sender address is easy to fake.

- Treat mailbox credentials and downloaded attachments as sensitive.
- Preserve UID/state tracking so restarts do not duplicate old mail.
- Keep SMTP replies threaded and safe around user-visible errors.

## Work Guidance

- Coordinate polling, dispatch prompts, and WebUI settings when adding account or routing behavior.

## Verification

- Smoke-test connection checks, polling, attachment handling, dispatch routing, and SMTP replies when practical.

## Child DOX Index

No child DOX files.
