# Windows Intelligence

Typed, read-only questions about the Windows machine Agent Zero runs on - processes, services, installed apps, events, ports, the registry - plus a few safe per-user settings, without the agent writing free-form PowerShell each time.

**Status: foundation.** This release has the building blocks: argument validation, compact capped output, secret redaction and a safe PowerShell runner. The `windows_info` and `windows_setting` tools themselves are added in the next phases.

How it stays safe:

- Arguments are validated values, never pasted into a command line or script.
- PowerShell scripts are fixed, scanned for read-only cmdlets, and receive their arguments as data.
- Results are size-capped and secrets (passwords, tokens, API keys, URL credentials) are masked.
- Anything that needs administrator rights is reported, never worked around - Agent Zero runs as a standard user.

When the tools land, note that system information goes to whichever model provider you use; with a local model such as LM Studio it stays on your PC.
