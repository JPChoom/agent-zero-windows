# Tool Execute Before Extensions DOX

## Purpose

- Own backend processing immediately before tool execution.

## Ownership

- Ordered Python files own the kill-switch gate (`_01_`), the host-bound secret guard (`_09_`), prior tool-output replacement and secret unmasking (`_10_`), parallel recursion guards (`_20_`), and audit capture (`_95_`).
- `_09_secret_destination_guard.py` must run before `_10_unmask_secrets.py`: it refuses calls that would send a secret bound with a `# hosts:` comment (`helpers/secrets.py get_host_bindings`) anywhere but those hosts, including browser typing into a page on another host or an undeterminable destination. It is `FAIL_LOUD`.

## Local Contracts

- `_01_kill_switch.py` refuses every tool while the kill switch is tripped, except read-only tools (`plugins/_permissions` `rules.classify`), `response`, and terminal `output`/`reset`. It is core on purpose (disabling a plugin must not disable it) and `FAIL_LOUD`; tools that act on the machine keep their own check as a second layer.
- Extensions merge by file name across agent, user, plugin and core folders, and the first occurrence wins: a file with the same name elsewhere replaces a gate. Never reuse a gate's file name for anything else.

- Unmask only values required by the target tool.
- Preserve safety checks and do not expose secrets to logs or unrelated tools.
- Keep ordering stable where replacement must occur before unmasking or execution.
- A gate that refuses by raising (here or in a plugin, on `tool_execute_before` or `tool_execute_after`) must set `FAIL_LOUD = True`. The dispatcher isolates extensions by default and swallows their exceptions, so without it the refusal is only logged and the tool runs anyway.

## Work Guidance

- Coordinate with secret handling, tool argument preparation, and plugin tool gates.

## Verification

- Smoke-test tool execution with masked secret arguments and prior-output references after changes.
- `pytest tests/test_tool_gates_fail_loud.py` (refusals reach the caller through the real dispatcher; every raising gate is `FAIL_LOUD`).

## Child DOX Index

No child DOX files.
