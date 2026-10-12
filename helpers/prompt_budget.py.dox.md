# prompt_budget.py DOX

## Purpose

- Own how much of the model's context window a prompt may really use: the window a local server actually loaded, a smaller working window after a provider refused a prompt as too long, and trimming of non-history extras.

## Ownership

- `prompt_budget.py` owns the implementation; this file owns its durable notes.
- Public: `effective_ctx_length(cfg, agent=None)`, `detect_server_window(cfg)`, `shrink_after_overflow(agent)`, `overflow_factor(agent)`, `is_context_overflow(exc)`, `shrink_extras(extras, excess)`, `OVERFLOW_FACTOR_KEY`.

## Runtime Contracts

- `effective_ctx_length` = min(configured `ctx_length`, window reported by a local server) x overflow factor. Only `lm_studio` (`/api/v0/models`, `loaded_context_length` of the loaded model) and `llama_cpp` (`/props`, `n_ctx`) are queried, on this PC, with a 1 s timeout and a 30 s cache; any failure falls back to the configured value. Cloud providers are never queried.
- Used by `History._get_ctx_size_for_history` (compression target), `_get_utility_input_budget` (summary input, without the factor) and `Agent._window_and_reserve` (`_fit_extras_to_window`, `_fit_history_to_window`).
- The overflow factor lives in agent data under a `_` key (not saved with the chat): `shrink_after_overflow` multiplies it by 0.85 down to 0.5; `plugins/_error_retry` gives back 0.02 per turn.
- `is_context_overflow` matches provider wording for a prompt that does not fit; it deliberately does not match per-minute rate-limit messages.
- `shrink_extras` returns a trimmed copy (the persistent extras are never modified): shortens solutions then memories, then drops in `DROP_ORDER`; date/time, agent info, goal and parallel jobs are never touched.

## Verification

- `pytest tests/test_prompt_budget.py`

## Child DOX Index

No child DOX files.
