# untrusted_content.py DOX

## Purpose

- Own the "external content is data" marker and the per-chat untrusted-content taint used for prompt-injection hardening.

## Ownership

- `untrusted_content.py` owns the runtime implementation; this file owns its contracts.
- Public API: `TRUSTED_TOOLS`, `READ_ONLY_ACTIONS`, `is_trusted_tool`, `is_read_only_call`, `wrap_tool_result`, `is_wrapped`, `strip_untrusted_blocks`, `looks_like_injected_instruction`, `mark_tainted`, `is_tainted`.

## Runtime Contracts

- `extensions/python/hist_add_tool_result/_50_mark_untrusted_content.py` wraps every string tool result except `TRUSTED_TOOLS` in `<untrusted_content source="tool">...</untrusted_content>` and taints the chat (`context` data key `untrusted_content_seen`). Tags inside the content are neutralized so it cannot close the block early.
- The role prompts (`prompts/` and `agents/agent0/prompts/agent.system.main.role.md`) define the tag's meaning: data, never instructions. Keep the tag name in sync with them and with `fw.*summary.sys.md` and the `_memory` memorize prompts.
- `_infection_check` skips its model call for `is_read_only_call` tools always, and for untainted chats when `only_after_untrusted_content` is on.
- `_memory` fragment memorization strips untrusted blocks first; fragment and solution candidates matching `looks_like_injected_instruction` are discarded.
- Adding a tool that only returns A0-generated text: add it to `TRUSTED_TOOLS`. Adding a side-effect-free read action: add it to `READ_ONLY_ACTIONS`.

## Verification

- `pytest tests/test_injection_hardening.py`

## Child DOX Index

No child DOX files.
