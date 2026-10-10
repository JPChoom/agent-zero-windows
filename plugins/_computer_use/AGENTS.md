# Computer Use Plugin DOX

## Purpose

- Own the `computer_use` tool: reading and operating Windows apps through their UI Automation tree via trycua's cua-driver, with background (no focus steal) input by default.

## Ownership

- `helpers/driver.py` owns finding `cua-driver.exe` (config `driver_path`, else newest `usr/cua-driver/<version>/`), starting the daemon on demand, telemetry opt-out, and `call` (JSON on stdin, one session label per chat).
- `helpers/policy.py` owns hard limits (no Agent Zero imports): secret/elevation processes, terminals, blocked and risky hotkeys, secret-field labels.
- `tools/computer_use.py` owns actions, gates, ownership tracking (registered in `helpers/workspace.py`: apps it launches belong to the launching chat and agent, pass to the chat that started a parallel job when the job ends, and are trusted only while the same process runs) and audit records.
- `prompts/agent.system.tool.computer_use.md` and `webui/config.html` own the agent prompt and settings UI.

## Local Contracts

- Never download or update the driver from code; installing it is a manual, user-approved step (README).
- Read actions (`apps`, `windows`, `inspect`, `screenshot`, `status`) need no `control_enabled`; they are listed in `_permissions/helpers/rules.py _READ_ACTIONS` - keep both in sync with `policy.READ_ACTIONS`.
- Input needs `control_enabled` (default false) and an untripped kill switch, and is audited before it runs.
- Policy refusals are final in every mode. Outside Bypass, input into windows the agent did not launch in this chat, foreground delivery and risky hotkeys go through `_permissions/helpers/ask.request_approval` unless the permission gate already asked for the call.
- `launch` passes `creates_new_application_instance: true` and marks a pid as owned only when it was not running before the launch.
- Ownership follows the agent chain of the chat (`helpers/workspace.owns_app` with the agent's number): an agent may act without the extra approval on apps it or a sub-agent under it launched; a superior's app asks, with that reason. `hand_over` (`pid`, `to`) gives an owned app to a sub-agent below; it is bookkeeping only (nothing reaches the app), so it is a read action in `policy.READ_ACTIONS` and `_permissions` `_READ_ACTIONS`.
- `close` only ends owned pids. Screenshots go to `tmp/computer_use/`, never into the chat as base64.

## Work Guidance

- Prefer element tokens over coordinates; keep the tool's output compact (`max_elements`).

## Verification

- `pytest tests/test_computer_use.py`
- Manual smoke test against an app that is not already open (e.g. `charmap`): launch, windows, inspect, set_value, close.

## Child DOX Index

No child DOX files.
