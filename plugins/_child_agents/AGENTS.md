# Child Agents Plugin DOX

## Purpose

- Own the Child agents surface: what each child agent of a chat is doing right now, with Stop and Open chat.

## Ownership

- `api/status.py` (`POST /plugins/_child_agents/status`) lists a chat's children (`helpers/child_agents.describe`) and stops one; a chat that is itself a child lists its parent's children.
- `webui/child-agents-store.js` (`$store.childAgents`) owns polling (every 3 s while mounted and visible), stop and open-chat.
- `webui/child-agents-panel.html` owns the layout and styles (shared by the floating modal and the right canvas); `webui/main.html` is the modal wrapper.
- `extensions/webui/` owns surface registration (`surfaces_register`, `right_canvas_register_surfaces`) and the docked panel.
- The data comes from `helpers/child_agents.py` (`progress`, `worktrees_of`, `describe`); the plugin only presents it.

## Local Contracts

- A row shows state (working / idle / chat deleted), the newest entry of the child's chat log as its current activity, step count, time of last activity (server clock, so a skewed browser clock cannot lie), the profile and, when the child works in a git worktree, its branch.
- Stop ends the child's run only: its chat and worktree stay, and the parent keeps working. Open chat switches to the child's chat; a child chat offers Open parent chat.
- The panel imports its store itself and starts polling from `x-init` inside the `$store.childAgents` gate, like the Workspace panel (the canvas restores a docked panel without loading `main.html`).
- Same A0W look as the Workspace panel; narrow containers stack the row actions under the row.

## Verification

- `pytest tests/test_child_agent_progress.py`
- Smoke-test in the dev server: open Child agents from the rail in a chat with children, stop a running child, narrow the window to phone width.

## Child DOX Index

No child DOX files.
