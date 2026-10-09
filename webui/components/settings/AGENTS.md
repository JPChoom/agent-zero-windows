# Settings Components DOX

## Purpose

- Own WebUI settings shell and built-in settings subsections.

## Ownership

- `settings.html` and `settings-store.js` own the settings shell and state.
- Subdirectories own settings areas such as agent, external, developer, MCP, backup, plugins, secrets, skills, tunnel, and A2A.
- `mcp/client/` owns the global/project MCP server manager, server search, raw JSON editor surface, examples modal, server tool detail modal, MCP scanner modal, scan checks, and scan prompt assets.
- `appearance/appearance.html` owns Settings > Appearance (theme, accent, material, wallpaper, live preview). It has no store of its own: it binds to `$store.preferences`, applies instantly, and stores per browser - no Save.
- Every settings section rendered in a tab must also be listed in that tab's `sections` in `settings-store.js` `TAB_ITEMS`, or it gets no navigation link.
- `external/security.html` + `external/security-store.js` own Settings > Security: the remote-access IP allowlist, blocked list and Access log viewer (`api/security_settings.py`, action `audit_log`; rows expand to the full JSON record), default permission mode and Bypass time limit (ordinary settings fields), and the Bypass password form (`api/permissions_bypass_password.py`). Allowlist saves are mirrored into `$store.settings` so the main Save never writes back a stale list.
- `skills/` owns skill listing, importing, standalone skill scanning, uploaded archive scan preparation UI, scanner modal, scan checks, and scan prompt assets.

## Local Contracts

- Keep settings payloads synchronized with backend APIs and plugin settings contracts.
- Do not store secrets in localStorage, URLs, or console output.
- Preserve Store Gating and modal footer conventions in settings components.
- MCP manager tool toggles write `disabled_tools` into the draft JSON and require Apply before changing the running MCP tool set.
- Confirmed MCP server removals apply immediately and refresh server status; other MCP manager draft edits still require Apply.

## Work Guidance

- Prefer subsection-local stores for complex settings areas.
- Coordinate plugin settings UI changes with `webui/components/plugins/` and `plugins/AGENTS.md`.
- Keep MCP scanner checks and prompt assets close to the MCP client modal so scanner behavior remains reviewable with the UI that invokes it.
- Keep Skills scanner checks and prompt assets close to the Skills settings section so scanner behavior remains reviewable with import and standalone scan entry points.
- Keep MCP manager search and toggle affordances consistent between global and project scope because both are rendered by the same client modal.

## Verification

- Smoke-test changed settings tabs and save/reload behavior after visible or API changes.

## Child DOX Index

No child DOX files.
