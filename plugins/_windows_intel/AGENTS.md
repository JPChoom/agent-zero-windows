# Windows Intelligence Plugin DOX

## Purpose

- Own typed, read-only Windows system queries (`windows_info`) and a small catalog of safe per-user settings (`windows_setting`), so the agent reads Windows state without writing free-form PowerShell. Roadmap: `usr/plans/v1.2-windows-intelligence.md` (private); this file documents what exists.

## Ownership

- `helpers/schema.py` owns the action catalog (actions, argument kinds, limits, `help_text`). Data only.
- `helpers/validate.py` owns argument validation: the only way model-supplied text reaches a source.
- `helpers/fmt.py` owns compact table output, size caps and secret redaction.
- `helpers/sources_ps.py` owns the PowerShell runner and the constant scripts (`SCRIPTS`), plus `scan_problems`, the read-only script scan.
- `helpers/config.py` owns resolved settings (`default_limit`, `max_limit`, `max_output_chars`, `redact_secrets`, `ps_timeout_seconds`).
- `helpers/sources_local.py` owns the in-process sources (psutil, winreg, win32): system, processes, services, disks, network, ports, windows, env, installed apps, startup, registry, and the registry access policy (`REGISTRY_ALLOW`, `REGISTRY_DENY`).
- `tools/windows_info.py` owns the agent tool: validate -> kill switch -> audit (registry, env, events, process command lines) -> source in a worker thread with a timeout -> capped text. `prompts/agent.system.tool.windows_info.md` keeps the always-on prompt to one action list; details come from `action=help`.

## Local Contracts

- No text from the model or from a query result may be placed into script text. Arguments reach PowerShell only as ASCII JSON in the `A0W_ARGS` environment variable, read with `ConvertFrom-Json`.
- Scripts are constants in `sources_ps.SCRIPTS`, run as the `-Command` argument of the system's own `powershell.exe` (absolute path) with `-NoProfile -NonInteractive`, no window, a timeout and at most two at once. Do not switch to stdin: PowerShell only runs a multi-line statement read from stdin after a blank line and silently drops it otherwise.
- `scan_problems` must pass for every script: allowlisted read-only cmdlets only (`ALLOWED_CMDLETS`; add one only after reading what it can do), no dangerous aliases at command position, no redirection, `&`, `-EncodedCommand`, risky .NET types or state-changing statics, ASCII and single-quoted strings only. `tests/test_windows_intel.py` scans every shipped script.
- Validation rejects unknown actions and arguments, names with characters outside `A-Za-z0-9 ._-/()+:@#`, registry paths outside HKLM/HKCU or with `..`, and out-of-range numbers; limits are capped by `max_limit`.
- Redaction (`fmt.redact`, `fmt.mask_value`) masks command-line passwords/tokens, `Authorization` headers, URL credentials, well-known token shapes and values whose *name* looks secret. Leave `redact_secrets` on.
- Administrator-only results become a `NeedsAdmin` message; Agent Zero never suggests elevating. The Security event log is refused up front: for a standard user Windows returns "no events", which would read as an empty log.
- Registry reads: only under `REGISTRY_ALLOW` roots, never paths containing a `REGISTRY_DENY` part (SAM, SECURITY, LSA, credentials, DPAPI Protect, Vault, Cryptography, IdentityCRL, TokenBroker, IntelliForms/Storage2). Values whose names look secret are masked; binary values show size and the first 16 bytes.
- `windows_info` is listed in `_permissions` `_READ_ONLY_TOOLS` (allowed in Plan mode and capped messaging chats). Its results stay untrusted content (not in `TRUSTED_TOOLS`).
- Expensive details are fetched only for narrowed queries (service account/binary with `name=`, task info only for the rows shown).

## Work Guidance

- New sources return rows to `fmt.table`; keep output compact and capped. Prefer in-process (psutil, winreg, win32) over PowerShell.

## Verification

- `pytest tests/test_windows_intel.py` (validation matrix and injection payloads, formatter caps, redaction, script scan fixtures, registry allow/deny, tool behaviour, a live PowerShell round trip proving arguments stay data, and a live read-only run of every action).

## Child DOX Index

No child DOX files.
