# channel_approvals.py DOX

## Purpose

- Own answering approval questions from a messaging channel: the question goes to the chat's channel with a four-character code, and a reply `yes CODE` / `no CODE` resolves it without reaching the agent.

## Ownership

- Public: `announce(agent, approval_id, question)`, `try_answer(context, message)`, `send(context, text, attachments)`, `can_answer_by_phone(agent)`, `forget(agent, approval_id)`, `APPROVAL_CHANNELS`, `SENDERS`.

## Runtime Contracts

- Called after `approval_registry.register` by `plugins/_permissions/helpers/ask.py`, `plugins/_safety_policy/.../_05_command_policy.py` and `plugins/_infection_check/helpers/checker.py`; a new approval site must announce too. The WebUI card is unchanged.
- Only `APPROVAL_CHANNELS` (telegram, whatsapp, discord, slack), never email (sender addresses are easy to fake), and only when the chat's bot/account has a non-empty allowlist (`plugins/<integration>/helpers/allowlist.channel_allowlist_set`). Senders are filtered by that allowlist before a message reaches `communicate`.
- Codes live in the governing chat's in-memory data (`CODES_KEY`), one per pending question, removed when answered. `extensions/python/_functions/agent/AgentContext/communicate/start/_05_channel_approval_reply.py` intercepts a matching reply and returns the chat's current task, so the agent never sees it; any other text passes through.
- `send` uses each integration's own reply function (`SENDERS`) and returns an error string; failures never raise.

## Verification

- `pytest tests/test_channel_approvals.py`.
