# workspace.py DOX

## Purpose

- Own the Agent Workspace registry: which chat and agent owns which Windows resources, hand-over when a parallel worker ends, and the merged listing behind the Workspace view.

## Ownership

- `workspace.py` owns the runtime implementation; this file owns its contracts.
- Public API: `Resource`, `register_app`, `find_app`, `owns_app`, `agent_number`, `hand_over`, `pass_up`, `assign`, `forget_app`, `apps`, `prune`, `release_context`, `parent_context_id`, `adopt`, `release`, `iter_chain`, `iter_agents`, `agent_names`, `end_agent`, `snapshot`, `process_start_time`, `PROVIDERS`, `MAIN_AGENT`.
- Callers: `plugins/_computer_use/tools/computer_use.py` (register on launch, `owns_app`, `forget_app`), `api/workspace.py`, `tools/call_subordinate.py` (`end_agent`), the core hook `extensions/python/_functions/agent/AgentContext/remove/start/_50_workspace_release.py`, and the providers below.

## Runtime Contracts

- In-memory only (lost on restart, like the apps' ownership used to be). Apps are the only kind stored here: terminals and browser tabs already belong to an agent/context, so they are read live from the `PROVIDERS` modules (`plugins/_code_execution/helpers/workspace_provider.py`, `plugins/_browser/helpers/workspace_provider.py`), each exposing `async resources()` and optionally `end_agent(agent)`.
- An app entry records `{pid, started}` (psutil start time). Ownership is trusted only while the same process is running: if the process exited or the pid was reused, the entry is dropped. `owns_app(context_id, pid)` is true only for an `active` entry owned by that chat.
- A resource has an owner (`owner_context`, `owner_agent` such as `A1`, `owner_profile`) and an origin (`origin_context`, `origin_agent`, `origin_job`) that never changes.
- Inside one chat agents form a chain (A0 delegates to A1, A1 to A2). `owns_app(context_id, pid, agent_no)` is true for the owner and every agent *above* it (lower number): an agent owns its own apps and its sub-agents', never those above it. Without `agent_no` it answers for the chat. An empty or unknown owner counts as A0.
- `hand_over(context_id, pid, from_no, to_name)`: an agent that owns an app gives it to a sub-agent below it (refused upwards or for apps it does not own). `pass_up(context_id, from_no)`: a replaced sub-agent's apps (and those below it) move to the agent above. `assign(id, context_id, agent)`: the user moves an app to another agent of the same chat. All audited (`workspace_handover`, `workspace_assign`).
- `release_context(context_id)` runs when a context is removed (core hook): a parallel worker's active apps pass to the chat that started it and to the agent there that started the job (`PARALLEL_PARENT_KEY` / `PARALLEL_PARENT_AGENT_KEY` in the context data, set by `helpers/parallel_tools.py`; only if that chat still exists), any other chat's apps become `orphaned` (still running). Both are audited (`workspace_handover`, `workspace_orphaned`). Apps are never closed automatically: they may hold unsaved work.
- `adopt(id, context_id)` gives an app to a chat's main agent (A0); `release(id)` stops tracking it (the app becomes "the user's": agents must ask before typing into it and cannot close it). Both audit with `by`.
- `end_agent(agent)` passes the replaced agent chain's apps up (`pass_up`) and asks every provider to end what it opened (terminal shells), used when `call_subordinate` replaces a subordinate (`reset=true`).
- `snapshot()` also returns `agents`: each listed chat's agent chain (`agent_names`), for the owner picker.
- At most `MAX_ENTRIES` (500) apps are tracked; the oldest go first.

## Verification

- `pytest tests/test_workspace.py tests/test_computer_use.py` (real contexts and real idle processes; the driver and terminal sessions are faked).

## Child DOX Index

No child DOX files.
