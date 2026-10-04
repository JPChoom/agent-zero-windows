# Safety Policy Plugin DOX

## Purpose

- Own the deterministic deny/approve floor for high-risk `code_execution_tool` calls, the download-host allowlist, and the shared Allow/Deny approval registry.

## Ownership

- `helpers/policy.py` owns command and source classification (categories, shell-out scanning, Python/Node HTTP-client destinations).
- `helpers/config.py` owns settings resolution and `add_allowed_host`.
- `helpers/approval_registry.py` owns pending human decisions (also used by `_permissions` and `_infection_check`); `has_pending()` lets the stall watchdog wait while one is outstanding.
- `extensions/python/tool_execute_before/_05_command_policy.py` owns the gate and the approval prompt; `extensions/webui/` and `webui/` own the in-chat buttons and the approval popup.
- `api/safety_policy_approve.py` (core `api/`) resolves decisions and remembers hosts.
- `README.md` documents behavior and limits for users.

## Local Contracts

- Regex/heuristic matching on literal text, not a sandbox (see README). Custom patterns always hard-deny and take precedence over approve-tier matches.
- Downloader destinations: URL hosts in curl/wget-style commands and, for python/nodejs source using an HTTP client (requests, httpx, urllib, fetch, axios...), every http(s) literal in the source. Allowlisted hosts (and subdomains) pass when the allowlist is enabled; others follow `tier_downloader`.
- "Always allow <host>" stores the host from server-side registry metadata, never from the browser.

## Work Guidance

- Keep README, `default_config.yaml`, and `webui/config.html` in sync with policy behavior.

## Verification

- `pytest tests/test_safety_policy.py tests/test_code_execution_access_tier.py`

## Child DOX Index

No child DOX files.
