# Sidebar Components DOX

## Purpose

- Own left sidebar layout, chat/task lists, top actions, and bottom preferences components.

## Ownership

- `left-sidebar.html` and `sidebar-store.js` own sidebar shell and shared state.
- `top-section/` owns header and quick actions.
- `chats/` owns chat list UI and state.
- `tasks/` owns task list UI and state.
- `bottom/` owns lower sidebar controls and the preferences panel. `bottom/preferences/preferences-store.js` is the single owner of appearance state (dark mode, accent color, material, wallpaper + fit; the wallpaper blob lives in IndexedDB and may be an image (body::before `--backdrop-image`) or a looping muted mp4/webm in a fixed `video.wallpaper-video` that pauses while the tab is hidden or under reduced motion); custom accent colors open the shared `$store.colorPicker` via `pickAccent(anchor)` for both the sidebar panel and Settings > Appearance.

## Local Contracts

- Preserve responsive sidebar behavior and collapsed/expanded state.
- Keep chat and task list updates compatible with WebSocket state sync.
- Contexts with `parent_context_id` render as indented children beneath their parent chat; they must remain selectable while hidden from the top-level chat list.
- Chat tree expand/collapse controls use a parent-only leading slot and must not consume normal chat row text margin.
- A restored selected parent chat with children auto-expands once during context hydration unless the user has already toggled it.
- The Tasks list is reserved for scheduler-backed task contexts and must not be used for chat-bound parallel children.
- Avoid text or controls overflowing fixed sidebar widths.
- Show/hide is the `.sidebar-edge-toggle` tab in `left-sidebar.html` (the header has no hamburger): it sits right of the header pill while open and at the screen edge while hidden; hiding slides both `#left-panel` and the header pill (`.is-offscreen`, moved with `left`, never a transform) off the left edge.
- Chats sit directly under the header; Tasks are pinned to the bottom of `.left-panel-top` (`margin-top: auto`), directly above Preferences.

## Work Guidance

- Coordinate navigation and state changes with WebSocket sync and chat/project stores.

## Verification

- Smoke-test sidebar collapse, chat list, task list, quick actions, and preferences after changes.

## Child DOX Index

No child DOX files.
