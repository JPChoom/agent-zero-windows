# Windows Intelligence Plugin DOX

## Purpose

- Own typed, read-only Windows system queries (`windows_info`) and a small catalog of safe per-user settings (`windows_setting`), so the agent reads Windows state without writing free-form PowerShell. Roadmap: `usr/plans/v1.2-windows-intelligence.md` (private); this file documents what exists.

## Ownership

- `helpers/schema.py` owns the action catalog (actions, argument kinds, limits, `help_text`). Data only.
- `helpers/validate.py` owns argument validation: the only way model-supplied text reaches a source.
- `helpers/fmt.py` owns compact table output, size caps and secret redaction.
- `helpers/sources_ps.py` owns the PowerShell runner and the constant scripts (`SCRIPTS`), plus `scan_problems`, the read-only script scan.
- `helpers/config.py` owns resolved settings (`default_limit`, `max_limit`, `max_output_chars`, `redact_secrets`, `ps_timeout_seconds`).
- Status: foundation only (validation, formatting, redaction, PowerShell runner). The tools, in-process sources, PowerShell scripts for events/tasks/devices, settings catalog and prompts arrive in later phases.

## Local Contracts

- No text from the model or from a query result may be placed into script text. Arguments reach PowerShell only as ASCII JSON in the `A0W_ARGS` environment variable, read with `ConvertFrom-Json`.
- Scripts are constants in `sources_ps.SCRIPTS`, run as the `-Command` argument of the system's own `powershell.exe` (absolute path) with `-NoProfile -NonInteractive`, no window, a timeout and at most two at once. Do not switch to stdin: PowerShell only runs a multi-line statement read from stdin after a blank line and silently drops it otherwise.
- `scan_problems` must pass for every script: allowlisted read-only cmdlets only (`ALLOWED_CMDLETS`; add one only after reading what it can do), no dangerous aliases at command position, no redirection, `&`, `-EncodedCommand`, risky .NET types or state-changing statics, ASCII and single-quoted strings only. `tests/test_windows_intel.py` scans every shipped script.
- Validation rejects unknown actions and arguments, names with characters outside `A-Za-z0-9 ._-/()+:@#`, registry paths outside HKLM/HKCU or with `..`, and out-of-range numbers; limits are capped by `max_limit`.
- Redaction (`fmt.redact`, `fmt.mask_value`) masks command-line passwords/tokens, `Authorization` headers, URL credentials, well-known token shapes and values whose *name* looks secret. Leave `redact_secrets` on.
- Administrator-only results become a `NeedsAdmin` message; Agent Zero never suggests elevating.

## Work Guidance

- New sources return rows to `fmt.table`; keep output compact and capped. Prefer in-process (psutil, winreg, win32) over PowerShell.

## Verification

- `pytest tests/test_windows_intel.py` (validation matrix and injection payloads, formatter caps, redaction, script scan fixtures, a live PowerShell round trip proving arguments stay data).

## Child DOX Index

No child DOX files.
