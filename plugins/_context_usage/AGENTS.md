# _context_usage Plugin DOX

## Purpose

- Live context-window usage indicator in the chat input bar.

## Ownership

- `api/context_usage_get.py` owns token-usage calculation for the selected chat.
- `extensions/webui/chat-input-bottom-actions-end/` and `webui/` own the indicator and its store.

## Local Contracts

- The indicator lives in `.chat-bottom-actions-bar`; follow the chat input DOX for bottom-row extensions.

## Work Guidance

## Verification

- Smoke-test the indicator updates while a chat runs.

## Child DOX Index

No child DOX files.
