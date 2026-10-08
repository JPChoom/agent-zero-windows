# Plugin Discovery DOX

## Purpose

- Own contextual plugin discovery cards and welcome-screen promotions.

## Ownership

- `plugin.yaml` owns metadata and always-enabled status.
- `extensions/` owns backend or WebUI discovery contributions.
- `webui/discovery-store.js` owns discovery UI state and actions.

## Local Contracts

- Discovery cards must be accurate, dismissible where appropriate, and avoid advertising already-complete setup.
- CTA actions must match supported welcome-screen action contracts.
- Keep card IDs unique and plugin-prefixed.
- Every built-in messaging channel (Telegram, Email, WhatsApp, Discord, Slack) has a feature card in `extensions/python/banners/10_discovery_cards.py` that disappears once its credentials are set. A new channel plugin must add its card there (a Material icon is fine when it has no thumbnail) and a case in `tests/test_discovery_channel_cards.py`.
- The Welcome screen `welcome-actions-end` surface renders feature channel cards plus the compact OAuth account-provider card; other hero discovery cards stay out of the lower welcome grid.
- Do not hide discovery cards solely because model setup is incomplete; model setup gating belongs to the chat thread.

## Work Guidance

- Prefer backend status checks before surfacing setup or integration prompts.

## Verification

- `pytest tests/test_discovery_channel_cards.py tests/test_welcome_composer_static.py`
- Smoke-test welcome-screen discovery cards, ordering, dismissal, and CTA behavior after changes.

## Child DOX Index

No child DOX files.
