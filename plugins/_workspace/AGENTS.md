# Workspace Plugin DOX

## Purpose

- Own the Workspace surface: a list of which agent owns which apps, terminal sessions and browser tabs, with Adopt, Release and Close.

## Ownership

- `webui/workspace-store.js` (`$store.workspace`) owns loading (polls every 4 s while mounted and visible), filters, grouping and actions.
- `webui/workspace-panel.html` owns the layout and styles (shared by the floating modal and the right canvas); `webui/main.html` is the modal wrapper.
- `extensions/webui/` owns surface registration (`surfaces_register`, `right_canvas_register_surfaces`) and the docked panel.
- The registry and API live outside the plugin: `helpers/workspace.py`, `api/workspace.py`.

## Local Contracts

- Group by chat, current chat first; orphaned apps (their chat was deleted) form their own group on top.
- Closing an app asks first, is disabled while Computer Use input is off, and the explanation is shown; apps are never closed automatically.
- Releasing explains that the app becomes the user's own again.
- Adopt is offered only for apps and only when a chat is open; it assigns the app to that chat's A0.
- When the owning chat has more than one agent, an app's owner chip is a picker (`assign`); the tooltip explains that the owner and the agents above it may use it without asking.
- Keep the A0W look of the File Browser (same command bar / status bar language); narrow containers stack row actions under the row.

## Verification

- `pytest tests/test_workspace.py`
- Smoke-test in the dev server: open the Workspace from the rail, release an app, narrow the window to phone width.

## Child DOX Index

No child DOX files.
