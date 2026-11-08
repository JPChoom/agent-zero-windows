# child_agent.py DOX

## Purpose

- Own the `child_agent.py` agent tool: named child agents in chats of their own (`helpers/child_agents.py`).

## Ownership

- `child_agent.py` owns argument parsing and the response; `helpers/child_agents.py` owns the lifecycle.
- Classes:
- `ChildAgent` (`Tool`)
  - `async execute(self, action=..., name=..., message=..., profile=..., wait=..., timeout=..., **kwargs)`
  - `get_log_object(self)`

## Runtime Contracts

- Actions: `start`/`message` (give a task; an existing child keeps its history), `result` (wait, optional `timeout`), `status`, `stop`, `forget`. Returns JSON; `break_loop` is False.
- A profile is validated with `call_subordinate._validate_subordinate_profile` and can only be set when the child is first started.
- `ChildAgentError` becomes a `RepairableException` the model can act on.
- Prompt: `prompts/agent.system.tool.child_agent.md`; capability actions are listed in `plugins/_capabilities/helpers/policy.KNOWN_ACTIONS`.

## Verification

- `pytest tests/test_child_agents.py`.
