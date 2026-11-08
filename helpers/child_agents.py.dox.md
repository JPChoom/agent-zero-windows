# child_agents.py DOX

## Purpose

- Own independent child agents: named agents in chats of their own, resumable by name, stoppable on their own, inside the parent's permission mode and capability limits.

## Ownership

- Public: `send(agent, name, message, profile, wait, timeout)`, `result(agent, name, timeout)`, `describe(parent)`, `stop(parent, name)`, `forget(parent, name)`, `stop_all(parent)`, `registry(parent)`, `find(parent, name)`, `normalize_name`, `ChildAgentError`, `CHILDREN_KEY`, `CHILD_OF_KEY`, `MAX_CHILDREN`.

## Runtime Contracts

- The parent's `CHILDREN_KEY` data maps names to child context ids and is saved with the chat; a child context is a USER chat with `parent_context_id`/`parent_context_kind: child` output data, so the sidebar nests it under the parent.
- `_bind` re-applies the runtime links on every run (keys with a leading `_` are not saved): `PARALLEL_WORKER_PARENT_CONTEXT_KEY` (so `parallel_tools.governing_context` returns the root chat for permission mode, messaging limits and approval cards; it follows up to `GOVERNING_DEPTH` levels) and the capability scopes (`plugins/_capabilities` `CONTEXT_SCOPES_KEY`, saved).
- A task runs as the child chat's own task (`communicate`), so the chat's Stop works and the parent continues with `wait: false`. A parent cancelled while waiting kills the child (`result`). Resetting or deleting a parent stops its children and grandchildren (`_functions/agent/AgentContext/{reset,remove}/start/_40_stop_child_agents.py`). `forget` keeps the child's chat for reading.
- A busy child is not given a second task; a profile is fixed at the first start.

## Verification

- `pytest tests/test_child_agents.py`.
