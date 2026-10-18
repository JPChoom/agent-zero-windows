# Speed Measurement Plugin DOX

## Purpose

- Own per-turn latency records for the local-speed work: where each turn's time goes, measured, so speed changes are judged by numbers.

## Ownership

- `helpers/perf.py` (core) owns the records, the turn aggregation, the event-loop stall probe and the JSONL files; this plugin only opens/closes turns and times tools.
- `extensions/python/monologue_start/_01_perf_turn_start.py` / `monologue_end/_99_perf_turn_end.py` open and close a turn for agent 0 and print the summary line.
- `extensions/python/tool_execute_before/_99_perf_tool_start.py` / `tool_execute_after/_00_perf_tool_end.py` bracket the tool call itself (last before-hook, first after-hook).
- `default_config.yaml` owns `print_summary`.

## Local Contracts

- Only agent 0 opens and closes a turn; sub-agents run inside their superior's turn and are charged to it.
- Model-call timing lives in `models.py` (`_run_unified`), hook timing in `helpers/extension.py` (`call_extensions_async`); a call's role comes from `a0_perf_role` set by `plugins/_model_config` builders (`main`, `utility`, `vision`; anything else is `other`).
- Records hold numbers, model names and chat ids only - never prompt, reasoning or response text. Files live in `usr/perf/` (git-ignored) and rotate at 5 MB.
- Measurement must never fail a turn: storage errors are swallowed.

## Work Guidance

- Add a measurement only with a matching field in the turn record and a test.

## Verification

- `pytest tests/test_perf.py`.

## Child DOX Index

No child DOX files.
