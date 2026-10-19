# Infection Check Plugin DOX

## Purpose

- Own prompt-injection safety checks over streamed reasoning/response content before tool execution.

## Ownership

- `helpers/checker.py` owns safety analysis orchestration and gate behavior.
- `extensions/` owns stream collection and tool-execution blocking hooks.
- `default_config.yaml`, `plugin.yaml`, `README.md`, and `webui/` own settings, metadata, behavior notes, and config UI.

## Local Contracts

- Preserve configured `thoughts` and `complete` analysis modes.
- Tool execution must wait for required safety verdicts.
- The gate skips side-effect-free local reads (`helpers/untrusted_content.is_read_only_call`) always, and skips chats that have not yet seen untrusted content while `only_after_untrusted_content` is true (default). Set it false to check every call from the start.
- A background check's verdict stands in for the gate only when the response it judged contains the exact tool call being gated (`_snapshot_covers`: same name, same arguments); a running covered check is awaited, never cancelled. A verdict on thoughts alone is never reused. In `thoughts` mode the background check starts once the tool call in the stream is complete.
- A chat with a safety-policy refusal (`plugins/_safety_policy/helpers/denials.py`) is checked on every gated call, tainted or not, and the refusals are put in front of the check model ("Safety Policy Refusals in This Chat"); rule H5 terminates workarounds.
- Exact calls (name + canonical arguments) that passed, or that the user allowed, are remembered per chat (`DATA_KEY_ALLOWED_CALLS`, last 200) and skip the model. Terminated calls are never remembered.
- `get_config` swaps an unedited copy of a previous default prompt (`_PREVIOUS_DEFAULT_PROMPTS`, SHA-256) for the current default; when the default prompt changes, add the old one's hash. Edited prompts are kept.
- Do not log or expose chain-of-thought or sensitive prompt content beyond intended warning flows.

## Work Guidance

- Keep termination and clarification loops bounded and explicit.

## Verification

- Smoke-test ok, clarify, and terminate verdicts around tool execution after changes.

## Child DOX Index

No child DOX files.
