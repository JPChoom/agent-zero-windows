# Changelog

All notable changes to Agent Zero for Windows. Versions are git tags (`vX.Y`, or `vX.Y.Z` for patch releases).

## v1.2.1

A security fix for permission refusals, a full access log, and in-app updates. **Update from v1.0, v1.1 or v1.2 as soon as you can.**

### Security
- **Fixed: refusals from the permission gate, the command safety floor and the coding completion gate were logged but not enforced** (v1.0 to v1.2). The tool ran anyway, so Plan mode, deny rules, clicking *Deny* on an approval card, an approval timing out, the denied-command floor and its kill-switch check did not stop anything. All three now block for real; new tests drive the real extension dispatcher, and any future gate that refuses this way must be marked to stay enforced.
- **Access log**: every sign-in, failed sign-in, lockout, sign-out, blocked request and remote visit (allowlisted or not) is recorded with address and port, how it arrived, allowlist match, country, Cloudflare request ID, browser, language, referrer, host, method, path, query, every request header and the address's history. Passwords, cookies, tokens and secret-looking query values are never stored. A remote sign-in raises a notification (high priority from a never-seen address). Browse it in *Settings > Security > Access log*; the file rolls over at 10 MB and keeps 20.

### New
- **In-app updates for native installs**: *Settings > Check for updates* shows the latest release of this fork from GitHub and installs it with one click (fast-forward of your git checkout, new packages if needed, one-click roll back). It refuses instead of overwriting local changes. The update check no longer contacts upstream's server.
- **Restarts keep Remote Control**: a running Cloudflare tunnel is handed to the restarted server and stays at the same address (sign in again afterwards).
- Discord and Slack cards on the welcome screen's *Connect Channels*.

### Changed
- The Bypass unlock dialog is sized to its content.
- Skill-learning tests use a neutral example.

## v1.2

Windows Intelligence: the agent understands the Windows machine it runs on.

### New
- **`windows_info`**: 14 typed, read-only queries - system (+GPU), processes, services, apps (+Store), startup, scheduled tasks, Event Viewer, devices, disks (+health), network, ports, open windows, registry, environment - with compact, size-capped, secret-masked output. Most run in-process in well under a second; PowerShell only for events, tasks, Store apps, devices, GPU and disk health.
- **`windows_setting`**: theme, file extensions, hidden files, taskbar alignment, power plan and wallpaper, each change audited, asked about in Manual mode and reported with the call to undo it.
- **Windows routing rule** in the system prompt: look with `windows_info`, change with `windows_setting` or the terminal, use `computer_use` only for app UIs and `desktop_control` last.
- Manual routing evaluation (`tests/manual/windows_routing_eval.py`) against a local model. With qwen3.8-27b in LM Studio, the right first tool was chosen for 23 of 24 Windows tasks, against 5 of 24 without these tools (the model otherwise improvised PowerShell for nearly everything, including settings changes).

### Security
- PowerShell queries are repo constants, scanned so they can only use allowlisted read-only cmdlets; arguments travel as JSON data, never inside the script or command line. Registry reads are limited to an allowlist and never touch credential stores. Administrator-only data (such as the Security log) is reported as such, never worked around.

### Changed
- The always-on skills catalog lists the `a0-*` plugin-development skills as one line (still searchable and loadable), and the desktop tool prompts are shorter, keeping the default prompt under 10,000 tokens.

## v1.1

Computer Use, learned skills, auditable memory, Discord and Slack, start at logon, and security hardening.

### New
- **Computer Use** plugin: operate Windows apps through their UI Automation tree via trycua's cua-driver, with background input (no mouse movement, no focus steal). Input off by default; hard refusals for sign-in/UAC/password-manager windows, terminals, lock/log-off keys and secret fields; approval before touching windows the agent didn't open.
- **Agent-learned skills** (`skill_learn`): after a long successful task the agent offers to save the procedure; drafts are checked and only installed after the user approves (in every mode), with versions kept.
- **Memory provenance and Health report**: source, trust, project, chat and last-used on every new memory; low-trust memories are flagged on recall; the dashboard reports duplicates, possible conflicts, stale and low-trust memories without changing anything.
- **Discord** and **Slack** (Socket Mode) integrations, allowlist-only (empty = nobody).
- **Start at logon**: optional per-user Startup entry and no-window launcher (Settings > Developer).

### Security
- Untrusted-content blocks carry a fresh random id per tool result (`<untrusted_content id="…">…</untrusted_content id="…">`), so a web page or file written in advance cannot contain the real closing tag. Tag-like text inside the content is neutralized in any case, spacing, HTML-entity or full-width form. Chats saved before this change still strip correctly for memory.
- Chats arriving over Telegram, WhatsApp, Email, Discord or Slack are capped at a configurable permission mode (default Manual).
- The command safety policy also denies agent commands that write a Run/RunOnce key or the Startup folder.
- `memory_save` refuses instruction-shaped text, like the automatic memorizers.
- Docs: a dedicated secondary PC is the intended setup; on a main PC it runs at your own risk.

### Cleanup
- Removed tracked `.bak` backup files and added `*.bak` to `.gitignore`.

## v1.0

First release of the Windows-native fork.

### Security
- Tunnel IP allowlist (default-deny); the "local" check ignores proxy/forwarding headers.
- Bypass permission mode is password-locked (separate from the login), auto-expires, and every restart, new chat and project switch returns to the safest mode.
- Generic sign-in page: no branding, no external requests.
- Prompt-injection hardening: external tool output is wrapped as `<untrusted_content>` (including the native Responses API path), memory never learns from it, and a secret bound to a host (`# hosts:` in the secrets file) is only ever sent to that host.
- Terminal Access plugin: authenticated, CSRF-protected, workspace-confined, command-screened, disabled by default.
- Controlled-shutdown chat persistence.

### Reliability
- Model calls time out by default and are limited per backend; a stall watchdog recovers hung jobs.
- No nested event loops (an agent could freeze permanently).
- Settings reads ~100x faster (no network call or git process per read).
- Time Travel snapshots serialized per repository; stale git locks cleared.
- Windows fixes: drive-letter paths in Document Query, no process-wide fake `fcntl`.

### WebUI
- New theme: accent colour with a themed colour picker, Solid/Glass/Enhanced materials, image or looping video wallpaper.
- Floating sidebar (edge tab to slide it away) and right-hand canvas; chat bubbles; accent buttons and toggles; composer actions bar that wraps cleanly; menus kept inside the viewport.
- Recently deleted chats (30-day trash) with Undo and Restore.
- Instant chat deletion.
- Plugins moved into the repository: Calendar, Personalities, Context Usage, Terminal Access.

### Project
- Removed upstream's Docker publishing and release automation; added a Windows test workflow.
- Test suite runs green on Windows; Linux/Docker-only tests are skipped via platform markers.
- Agent environment prompt and maintenance scripts use the real install path.
