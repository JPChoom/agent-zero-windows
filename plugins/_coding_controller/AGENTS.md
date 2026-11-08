# Coding Controller Plugin DOX

## Purpose

- Own the coding quality gate: after the agent edits a project, run its lint/build/test commands and block a false "done" response until they pass, with a bounded, checkpointed repair loop, optional read-only review and diagnosis.
- Off by default (`enforce_completion_gate: false`); enabled per project once its gate commands are verified.

## Ownership

- `extensions/python/text_editor_*_after/_15_track_edit.py` mark a project dirty when `_text_editor` changes a file in it.
- `extensions/python/tool_execute_after/_80_completion_gate.py` gates the `response` tool (`FAIL_LOUD`, listed in `helpers/extension.py PROTECTED_GATES`).
- `tools/coding_gate.py` runs the gate on request (a normal tool, so the permission gate applies to it).
- `helpers/quick_check.py` and `extensions/python/tool_execute_after/_70_quick_check.py` own the syntax check after every text_editor write or patch (`quick_check`, on by default).
- `helpers/task_worktrees.py`, `tools/coding_task.py` and `prompts/agent.system.tool.coding_task.md` own a git worktree per coding task.
- `helpers/gate_controller.py`, `helpers/adapters/*` and `helpers/process_runner.py` own detecting the project kind and running its commands; `helpers/checkpoint.py` owns checkpoints and rollback; `helpers/session_state.py` dirty roots and baselines; `helpers/reviewer.py` / `helpers/diagnostician.py` the optional sub-agents.
- `default_config.yaml`, `webui/config.html` and `README.md` own settings, their UI and user docs.

## Local Contracts

- Project build/test commands execute whatever the project defines, so before the completion gate runs them it applies the chat's permission mode (`_may_run_project_commands`, tool name `coding_completion_gate`): Plan never runs them, Manual and Accept-edits ask once per project root per chat (a decline is remembered for that chat), Auto and Bypass run them.
- Only new failures beyond a project's baseline block a turn; a worse repair attempt is rolled back to its checkpoint.
- The quick check parses only (compile(), json, yaml, tomllib; `node --check` for JavaScript when Node exists), never runs project code, and adds its finding to the same tool result; any failure of the check itself says nothing.
- `coding_task` worktrees live in `<workdir>/.worktrees/<repo>-<name>` on branch `a0/<name>`, registered in chat data (`coding_tasks`). `merge` is fast-forward only and refuses uncommitted task work, a main checkout on another branch or with uncommitted changes, and a base that moved on. Commits and merges are ordinary tool calls, so the permission mode and capability policies apply.
- The read-only `coding-reviewer` and `coding-diagnostician` ship `agents/<profile>/capabilities.yaml` (text_editor:read, read_diff), so they cannot write through a child agent, `parallel`, the browser or MCP either.
- Commands run through `process_runner` with a timeout (`command_timeout_seconds`), never through the interactive terminal.

## Work Guidance

- Keep adapters declarative (marker files -> commands) and their output parsing tolerant; unparsed output must still produce a pass/fail result.

## Verification

- `pytest tests/test_coding_controller*.py tests/test_coding_gate_permissions.py`

## Child DOX Index

No child DOX files.
