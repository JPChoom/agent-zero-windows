# perf.py DOX

## Purpose

- Own latency measurement for the local-speed work (v1.4 part 2, item 0): model calls, extension hooks, tools and event-loop stalls, per turn.

## Ownership

- `perf.py` owns the runtime implementation; `plugins/_perf` opens/closes turns and times tools.
- Public API: `start_model_call(model, role, prompt_chars) -> ModelCall` (`slot_acquired`, `chunk`, `finish`), `turn_start(context_id, agent_name)`, `turn_end(context_id) -> dict | None`, `add_hook_time`, `add_tool_time`, `format_turn(record) -> str`, `estimate_tokens`, `set_enabled`, `CONTEXT_ID` (contextvar), `CALLER` / `BACKGROUND` (contextvars) and the `tagged(caller, background=False)` decorator that sets them around an async function, `read_records(name, since)`, `latency_for(context_id, since)` (totals for one chat plus background calls in the window; used by `tests/manual/windows_workflow_benchmark.py`).

## Runtime Contracts

- `models.LiteLLMChatWrapper._run_unified` records every call: queue wait (until the backend slot from `helpers/model_concurrency` is held), time from slot to first chunk, total time, estimated prompt/reasoning/response tokens (characters / 4) and generation speed. A call with no running turn in its task (background thread, deferred task) is marked `background`.
- Each call records its `caller` (empty for the agent's own turn; `infection_check`, `memorize_fragments`, `memorize_solutions`, `memory_consolidation`, `memory_recall`, `rename_chat`, `history_compression`, `chat_compaction` are tagged at their call sites) and `background` (tagged background work, or no turn in its task).
- `prompt_reuse(context_id, key, messages)` (called for main-model calls, key `main:<agent>`, and for the infection check, key `infection_check`): fraction of the previous prompt unchanged from the start and how far from the end the first change is (1 = only the per-turn extras); recorded as `prompt_kept` / `prompt_changed_from_end` and shown as "prompt unchanged N%" in the turn line.
- `waiting_for_user()` wraps every wait for a person's approval: the time counts as the turn's `user_wait_s` and not as hook time. New approval waits must use it.
- `live_state()` serves the sidebar speed counter from `_live_calls`: the newest visible answer (phase reading/thinking/writing, rate over the last 3 s) and the last one finished.
- A call that does not stream (`ModelCall.streamed` False, set from `models._run_unified`) gets its whole answer at once, so it records `first_token_s: None` and `streamed: false`; the turn line says "not streamed" instead of a first-token time.
- `helpers/extension.call_extensions_async` charges each extension's time to the agent's chat turn.
- The event-loop probe (one task per loop, 100 ms sleep) reports the largest oversleep and the count over 100 ms during a turn: time when every chat and websocket on that loop was blocked.
- Writes `usr/perf/model_calls.jsonl` and `usr/perf/turns.jsonl`, one JSON object per line, rotated to `.1` past 5 MB. Numbers, model names and chat ids only, never text. Storage errors are swallowed; measurement never breaks a turn.

## Verification

- `pytest tests/test_perf.py`.
