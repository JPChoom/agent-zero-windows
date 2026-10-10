# workspace.py DOX

## Purpose

- Own the Agent Workspace registry: which chat and agent owns which Windows resources, hand-over when a parallel worker ends, and the merged listing behind the Workspace view.

## Ownership

- `workspace.py` owns the runtime implementation; this file owns its contracts.
- Public API: `Resource`, `register_app`, `find_app`, `owns_app`, `forget_app`, `apps`, `prune`, `release_context`, `parent_context_id`, `adopt`, `release`, `iter_chain`, `iter_agents`, `end_agent`, `snapshot`, `process_start_time`, `PROVIDERS`.
- Callers: `plugins/_computer_use/tools/computer_use.py` (register on launch, `owns_app`, `forget_app`), `api/workspace.py`, `tools/call_subordinate.py` (`end_agent`), the core hook `extensions/python/_functions/agent/AgentContext/remove/start/_50_workspace_release.py`, and the providers below.

## Runtime Contracts

- In-memory only (lost on restart, like the apps' ownership used to be). Apps are the only kind stored here: terminals and browser tabs already belong to an agent/context, so they are read live from the `PROVIDERS` modules (`plugins/_code_execution/helpers/workspace_provider.py`, `plugins/_browser/helpers/workspace_provider.py`), each exposing `async resources()` and optionally `end_agent(agent)`.
- An app entry records `{pid, started}` (psutil start time). Ownership is trusted only while the same process is running: if the process exited or the pid was reused, the entry is dropped. `owns_app(context_id, pid)` is true only for an `active` entry owned by that chat.
- A resource has an owner (`owner_context`, `owner_agent` such as `A1`, `owner_profile`) and an origin (`origin_context`, `origin_agent`, `origin_job`) that never changes.
- `release_context(context_id)` runs when a context is removed (core hook): a parallel worker's active apps pass to the chat that started it (`PARALLEL_PARENT_KEY` in the context data, only if that chat still exists), any other chat's apps become `orphaned` (still running). Both are audited (`workspace_handover`, `workspace_orphaned`). Apps are never closed automatically: they may hold unsaved work.
- `adopt(id, context_id)` gives an app to a chat; `release(id)` stops tracking it (the app becomes "the user's": agents must ask before typing into it and cannot close it). Both audit with `by`.
- `end_agent(agent)` asks every provider to end what a replaced agent chain opened (terminal shells), used when `call_subordinate` replaces a subordinate (`reset=true`).
- At most `MAX_ENTRIES` (500) apps are tracked; the oldest go first.

## Verification

- `pytest tests/test_workspace.py tests/test_computer_use.py` (real contexts and real idle processes; the driver and terminal sessions are faked).

## Child DOX Index

No child DOX files.
