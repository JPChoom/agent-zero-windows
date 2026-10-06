# Start at Logon Plugin DOX

## Purpose

- Own starting Agent Zero in the background at Windows sign-in, as an opt-in the user switches on in Settings > Developer.

## Ownership

- `helpers/startup.py` owns the single per-user Startup entry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `AgentZeroForWindows`), its status (including Task Manager's StartupApproved switch), enable and disable. Registry access goes through `_Registry` so tests use a fake.
- `launch_agent_zero.pyw` owns the launch: run by `.venv\Scripts\pythonw.exe`, exits if the WebUI port already answers, otherwise starts `.venv\Scripts\python.exe run_ui.py` with `CREATE_NO_WINDOW` (a hidden console that child terminals and the tunnel inherit), logging to `logs/autostart.log` (rotated at 5 MB).
- `api/autostart.py` (actions status/enable/disable) and `webui/config.html` own the switch.

## Local Contracts

- Off by default; only the signed-in, CSRF-checked WebUI turns it on. The agent cannot: `_safety_policy` hard-denies commands naming Run/RunOnce keys or the Startup folder.
- Per-user and non-admin: no Scheduled Task, service or machine-wide key.
- Enable clears a Task Manager "disabled" flag for the value; disable removes both values. Turn it off before deleting the plugin or moving the install, or the entry points at a missing launcher.
- The port comes from `usr/.env` `WEB_UI_PORT`, falling back to 5000 like `helpers/runtime.get_web_ui_port`.

## Verification

- `pytest tests/test_autostart.py` (fake registry; real child process from a temp folder).
- Manual: run the launcher with `pythonw.exe` while Agent Zero is running - `logs/autostart.log` gains an "already answers" line and nothing else starts.

## Child DOX Index

No child DOX files.
