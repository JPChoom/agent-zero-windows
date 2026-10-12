# Error Retry Plugin DOX

## Purpose

- Own retry behavior for unexpected critical exceptions in agent loops.

## Ownership

- `extensions/` owns retry counter reset and critical-exception retry hooks.
- `default_config.yaml` owns retry count defaults.
- `webui/config.html` owns settings UI.
- `plugin.yaml` and `README.md` own metadata and behavior notes.

## Local Contracts

- A context-window overflow (`helpers/prompt_budget.is_context_overflow`) is handled before the generic retry, on its own counter (`MAX_OVERFLOW_RETRIES` per turn): the chat's working window shrinks (`shrink_after_overflow`), history is compressed, a short note (not the long error) goes into history, and the turn is retried. The window grows back 2% per turn.

- Do not retry controlled flow exceptions such as `HandledException` and `RepairableException`.
- Keep retry counts scoped per monologue.
- Preserve clear agent-facing history injection when retrying a critical exception.

## Work Guidance

- Keep retry behavior conservative and observable through logs/UI.

## Verification

- Test or simulate critical, handled, and repairable exception paths after hook changes.

## Child DOX Index

No child DOX files.
