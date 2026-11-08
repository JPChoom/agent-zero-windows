# Infection Check Plugin DOX

## Purpose

- Own prompt-injection safety checks over streamed reasoning/response content before tool execution.

## Ownership

- `helpers/checker.py` owns safety analysis orchestration and gate behavior; `helpers/shadow.py` owns the compare-only shadow check.
- `extensions/` owns stream collection and tool-execution blocking hooks.
- `default_config.yaml`, `plugin.yaml`, `README.md`, and `webui/` own settings, metadata, behavior notes, and config UI.

## Local Contracts

- Fails closed. An action nobody checked does not run: no verdict tag is `NO_VERDICT`, never "ok" (`parse_result`); a failed or verdict-less utility call retries once on the Main model with thinking off (`_run_check`, `_main_model`); if no model answers, `_decide_unchecked` puts it to the user as a clarification (no answer means blocked; `clarify_mode: agent` blocks outright, because the agent is what is being checked); any other error in `gate()` blocks; a stop during the check propagates (`asyncio.CancelledError` is never swallowed while `_stopping()`). `model: main` also judges without thinking. Add a test in `tests/test_infection_fails_closed.py` for any new way out of `_gate_inner`.
- `shadow_utility` (off by default) starts `shadow.start` after the Main model's verdict: Utility judges the same messages in the background, one at a time, and verdicts, timing and an input hash go to `usr/perf/safety_shadow.jsonl`. Nothing reads it back, a failure cannot reach the verdict, and it uses `build_utility_model` so it can't fall back to Main. Summarize with `tests/manual/safety_shadow_report.py`. Moving the check to a smaller model needs that evidence and an explicit policy change: on 2026-11-06 the Dell's 9B model allowed a hostile case in the corpus.
- A pending tool call is always judged, even when nothing was collected from the stream (a native function call can arrive without streamed text); only a gate call with no logs and no tool returns early.
- Preserve configured `thoughts` and `complete` analysis modes.
- Tool execution must wait for required safety verdicts.
- The gate skips side-effect-free local reads (`helpers/untrusted_content.is_read_only_call`) always, and skips chats that have not yet seen untrusted content while `only_after_untrusted_content` is true (default). Set it false to check every call from the start.
- A background check's verdict stands in for the gate only when the response it judged contains the exact tool call being gated (`_snapshot_covers`: same name, same arguments); a running covered check is awaited, never cancelled. A verdict on thoughts alone is never reused. In `thoughts` mode the background check starts once the tool call in the stream is complete.
- A chat with a safety-policy refusal (`plugins/_safety_policy/helpers/denials.py`) is checked on every gated call, tainted or not, and the refusals are put in front of the check model ("Safety Policy Refusals in This Chat"); rule H5 terminates workarounds.
- The check shows history from `history_window_start(count, history_size)`: anchored, moving in steps of `history_size // 2`, so the prompt prefix stays the same across steps and a local server reuses it (a window sliding one message per step was re-read in full every tool call).
- `build_check_messages` sends one message per history entry and the output section as the last message. Hybrid models such as Qwen3.8 can only rewind to llama-server's checkpoints (message boundaries and just before the end); history and output in one message left only the end of the system prompt to rewind to (33k tokens, 16 s per check; split: 5.5k, 4.8 s). Keep the two section headings: the prompt names them.
- The last message ends with `CHECK_REMINDER`, which repeats the steps in short form: split up, the rules sit far back and hostile cases softened to `<clarify>` (2 of 9). Keep it in step with the prompt's steps, and run `tests/manual/infection_check_corpus.py --repeats 4` after changing either or the message shape; one run proves nothing, verdicts move between runs.
- Exact calls (name + canonical arguments) that passed, or that the user allowed, are remembered per chat (`DATA_KEY_ALLOWED_CALLS`, last 200) and skip the model. Terminated calls are never remembered.
- `get_config` swaps an unedited copy of a previous default prompt (`_PREVIOUS_DEFAULT_PROMPTS`, SHA-256) for the current default; when the default prompt changes, add the old one's hash. Edited prompts are kept.
- Do not log or expose chain-of-thought or sensitive prompt content beyond intended warning flows.

## Work Guidance

- Keep termination and clarification loops bounded and explicit.

## Verification

- Smoke-test ok, clarify, and terminate verdicts around tool execution after changes.

## Child DOX Index

No child DOX files.
