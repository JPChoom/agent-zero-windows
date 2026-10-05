# plugin_review.py DOX

## Purpose

- Shared plumbing for `plugins/_plugin_scan` and `plugins/_plugin_validator`: run a checklist prompt once in a disposable agent context and return the report.

## Ownership

- `plugin_review.py` owns the runtime implementation; this file owns its contracts.
- Functions: `run_scoped_review`, `queue_prompt_message`, `start_queued_agent`. Class: `ChecklistPromptBuilder`.

## Runtime Contracts

- `ChecklistPromptBuilder` loads a `{checks.json, prompt.md}` pair (cached) and fills the fields both plugins share.
- `run_scoped_review` always cleans up its temporary context.
- The review prompt treats the scanned plugin as untrusted data.

## Verification

- `pytest tests/test_plugin_scan_prompt.py tests/test_plugin_review_gate.py`
