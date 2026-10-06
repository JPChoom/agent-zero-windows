# Windows Intelligence

Typed, read-only questions about the Windows machine Agent Zero runs on - processes, services, installed apps, events, ports, the registry - plus a few safe per-user settings, without the agent writing free-form PowerShell each time.

**`windows_info`** answers, in compact capped tables: `system` (+GPU), `processes`, `services`, `apps` (+Store), `startup`, `tasks`, `events`, `devices`, `disks` (+health), `network`, `ports`, `windows`, `registry`, `env`. The agent sees one line listing them and asks `action=help` for details. Most answers take well under a second; PowerShell is used only for events, scheduled tasks, Store apps, devices, GPU and disk health.

How it stays safe:

- Arguments are validated values, never pasted into a command line or script.
- PowerShell scripts are fixed, scanned for read-only cmdlets, and receive their arguments as data.
- Results are size-capped and secrets (passwords, tokens, API keys, URL credentials) are masked.
- Anything that needs administrator rights is reported, never worked around - Agent Zero runs as a standard user.

**Privacy:** what the agent reads (process names, window titles, installed apps, event messages) is sent to whichever model provider you use. With a local model such as LM Studio it never leaves your PC.
