# Code Execution Plugin DOX

## Purpose

- Own terminal, Python, and Node.js code execution through persistent local or SSH-backed sessions.

## Ownership

- `tools/` owns the code execution and input tools.
- `helpers/` owns local shell, SSH shell, and TTY session management; `helpers/workspace_provider.py` lists terminal sessions for the Workspace view and ends them deterministically.
- `prompts/` owns execution prompt and runtime response fragments.
- `default_config.yaml`, `plugin.yaml`, `extensions/`, and `webui/` own settings, metadata, hooks, and UI config.

## Local Contracts

- Keep session concurrency, timeout, streaming, and reset behavior predictable.
- Explicitly target local versus SSH execution runtimes.
- Do not hardcode secrets, SSH credentials, or local user paths.
- `__del__` methods on session objects (`TTYSession`, `LocalInteractiveSession`) must stay synchronous and never run or nest an event loop (`asyncio.run`, `run_until_complete`): garbage collection can fire mid-task-step, and a nested loop there drops that task's wakeup and freezes the agent permanently. Graceful shutdown belongs to callers that `await close()`.
- Terminal sessions are stored per agent (`agent.get_data("_cet_state")`). They are ended (shell only, never its process tree, so GUI apps started from it keep running) by the `AgentContext` remove/reset hooks in `extensions/python/_functions/`, and when `call_subordinate` replaces a subordinate (`helpers/workspace.end_agent`), instead of whenever garbage collection runs. SSH sessions keep their own lifecycle.
- Use `tty_session._SIGKILL`, not `signal.SIGKILL`, which does not exist on Windows.

## Work Guidance

- Preserve long-running command output retrieval and busy-session guards when changing execution flow.

## Verification

- Smoke-test terminal, Python, Node.js, output polling, and reset paths after tool changes.

## Child DOX Index

No child DOX files.
