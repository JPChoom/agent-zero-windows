# Coding Controller Plugin DOX

## Purpose

- Own the coding quality gate: after the agent edits a project, run its lint/build/test commands and block a false "done" response until they pass, with a bounded, checkpointed repair loop, optional read-only review and diagnosis.
- Off by default (`enforce_completion_gate: false`); enabled per project once its gate commands are verified.

## Ownership

- `extensions/python/text_editor_*_after/_15_track_edit.py` mark a project dirty when `_text_editor` changes a file in it.
- `extensions/python/tool_execute_after/_80_completion_gate.py` gates the `response` tool (`FAIL_LOUD`, listed in `helpers/extension.py PROTECTED_GATES`).
- `tools/coding_gate.py` runs the gate on request (a normal tool, so the permission gate applies to it).
- `helpers/gate_controller.py`, `helpers/adapters/*` and `helpers/process_runner.py` own detecting the project kind and running its commands; `helpers/checkpoint.py` owns checkpoints and rollback; `helpers/session_state.py` dirty roots and baselines; `helpers/reviewer.py` / `helpers/diagnostician.py` the optional sub-agents.
- `default_config.yaml`, `webui/config.html` and `README.md` own settings, their UI and user docs.

## Local Contracts

- Project build/test commands execute whatever the project defines, so before the completion gate runs them it applies the chat's permission mode (`_may_run_project_commands`, tool name `coding_completion_gate`): Plan never runs them, Manual and Accept-edits ask once per project root per chat (a decline is remembered for that chat), Auto and Bypass run them.
- Only new failures beyond a project's baseline block a turn; a worse repair attempt is rolled back to its checkpoint.
- Commands run through `process_runner` with a timeout (`command_timeout_seconds`), never through the interactive terminal.

## Work Guidance

- Keep adapters declarative (marker files -> commands) and their output parsing tolerant; unparsed output must still produce a pass/fail result.

## Verification

- `pytest tests/test_coding_controller*.py tests/test_coding_gate_permissions.py`

## Child DOX Index

No child DOX files.
