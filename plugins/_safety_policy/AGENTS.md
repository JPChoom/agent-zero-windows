# Safety Policy Plugin DOX

## Purpose

- Own the deterministic deny/approve floor for high-risk `code_execution_tool` calls (and `input` tool keystrokes and `code_execution_remote` calls, which reach a shell; `_as_code_execution` in `_05_command_policy.py` must classify every tool that sends text to a shell), the download-host allowlist, and the shared Allow/Deny approval registry.

## Ownership

- `helpers/policy.py` owns command and source classification (categories, shell-out scanning, Python/Node HTTP-client destinations).
- `helpers/config.py` owns settings resolution and `add_allowed_host`.
- `helpers/denials.py` owns the per-chat list of refusals (read by `_infection_check` for rule H5 and its always-check-after-a-refusal rule).
- `helpers/startup_watch.py` owns the startup tripwire: snapshot, compare and undo of Run/RunOnce values, Startup folders, scheduled tasks (outside `\Microsoft`) and services; `extensions/python/tool_execute_before/_90_startup_tripwire.py` snapshots before a tool, `extensions/python/tool_execute_after/_01_startup_tripwire.py` compares, undoes, records and stops, and `extensions/python/monologue_end/_01_startup_tripwire.py` checks once more when a turn ends (a tool that raised never reaches tool_execute_after) and undoes without raising.
- `helpers/approval_registry.py` owns pending human decisions (also used by `_permissions` and `_infection_check`); `has_pending()` lets the stall watchdog wait while one is outstanding.
- `extensions/python/tool_execute_before/_05_command_policy.py` owns the gate and the approval prompt; `extensions/webui/` and `webui/` own the in-chat buttons and the approval popup.
- `api/safety_policy_approve.py` (core `api/`) resolves decisions and remembers hosts.
- `README.md` documents behavior and limits for users.

## Local Contracts

- Regex/heuristic matching, not a sandbox (see README). Every category (and custom pattern) is matched against the command as written and against `normalize_text` (joined quoted pieces, no string prefixes, escapes or quotes). Custom patterns always hard-deny and take precedence over approve-tier matches.
- Python/Node source is checked for logon-autorun paths (`_PERSISTENCE_PATH_PATTERNS`) everywhere in the source, not only inside shell-out calls.
- Every refusal message carries `DO_NOT_WORK_AROUND` and is recorded with `denials.record`; never phrase a refusal as an invitation to find another way.
- The startup tripwire fails closed (`startup_tripwire` is off only on an explicit false), never touches `OWN_RUN_VALUES` (Agent Zero's autostart), moves rather than deletes files and task definitions (`usr/safety_quarantine/`), and ends the task with `HandledException`. Its three hooks are in `helpers/extension.PROTECTED_GATES`.
- Downloader destinations: URL hosts in curl/wget-style commands and, for python/nodejs source using an HTTP client (requests, httpx, urllib, fetch, axios...), every http(s) literal in the source. Allowlisted hosts (and subdomains) pass when the allowlist is enabled; others follow `tier_downloader`.
- "Always allow <host>" stores the host from server-side registry metadata, never from the browser.

## Work Guidance

- Keep README, `default_config.yaml`, and `webui/config.html` in sync with policy behavior.

## Verification

- `pytest tests/test_safety_policy.py tests/test_code_execution_access_tier.py tests/test_safety_evasion.py`

## Child DOX Index

No child DOX files.
