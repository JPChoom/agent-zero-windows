# perf.py DOX

## Purpose

- Own latency measurement for the local-speed work (v1.4 part 2, item 0): model calls, extension hooks, tools and event-loop stalls, per turn.

## Ownership

- `perf.py` owns the runtime implementation; `plugins/_perf` opens/closes turns and times tools.
- Public API: `start_model_call(model, role, prompt_chars) -> ModelCall` (`slot_acquired`, `chunk`, `finish`), `turn_start(context_id, agent_name)`, `turn_end(context_id) -> dict | None`, `add_hook_time`, `add_tool_time`, `format_turn(record) -> str`, `estimate_tokens`, `set_enabled`, `CONTEXT_ID` (contextvar), `read_records(name, since)`, `latency_for(context_id, since)` (totals for one chat plus background calls in the window; used by `tests/manual/windows_workflow_benchmark.py`).

## Runtime Contracts

- `models.LiteLLMChatWrapper._run_unified` records every call: queue wait (until the backend slot from `helpers/model_concurrency` is held), time from slot to first chunk, total time, estimated prompt/reasoning/response tokens (characters / 4) and generation speed. A call with no running turn in its task (background thread, deferred task) is marked `background`.
- `helpers/extension.call_extensions_async` charges each extension's time to the agent's chat turn.
- The event-loop probe (one task per loop, 100 ms sleep) reports the largest oversleep and the count over 100 ms during a turn: time when every chat and websocket on that loop was blocked.
- Writes `usr/perf/model_calls.jsonl` and `usr/perf/turns.jsonl`, one JSON object per line, rotated to `.1` past 5 MB. Numbers, model names and chat ids only, never text. Storage errors are swallowed; measurement never breaks a turn.

## Verification

- `pytest tests/test_perf.py`.
