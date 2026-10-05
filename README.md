# Agent Zero for Windows

An unofficial, community fork of [Agent Zero](https://github.com/agent0ai/agent-zero) that runs **natively on Windows** - no Docker, no WSL, no Linux container. It adds a security-hardened remote-access model, a new WebUI theme, and a set of reliability fixes.

> **Not affiliated with or endorsed by Agent Zero, s.r.o.** "Agent Zero" and its logo are theirs. This fork keeps the name in the app for compatibility and credits the original project. If you want the official, Docker-based Agent Zero, use the [upstream repository](https://github.com/agent0ai/agent-zero).

## What's different from upstream

**Runs on Windows.** The agent works in PowerShell and Windows paths, and its prompt is filled in with your real install location instead of a fixed folder.

**Security hardening**
- **Tunnel IP allowlist.** Remote access through a tunnel is default-deny: only addresses you list can sign in. The check ignores proxy headers, so a tunnel client is never mistaken for "local".
- **Locked Bypass mode.** The "Bypass permissions" mode needs its own password (separate from the login), expires automatically (configurable in *Settings > Security*), and is reset to the safest mode on every restart, new chat and project switch.
- **Generic sign-in page** with no branding and no external requests.
- **Prompt-injection hardening.** Tool output from outside the agent (web pages, files, command output) is wrapped as untrusted data, the agent's memory never learns from it, and a destination guard blocks sending secrets to external hosts.
- **Per-chat permission modes** (Plan, Manual, Accept edits, Auto, Bypass) with approval prompts and a deterministic floor of denied commands.

**Reliability**
- Model calls time out by default and are limited per backend, so a stuck local model no longer freezes everything; a stall watchdog recovers hung jobs.
- No nested event loops, which could freeze an agent permanently.
- Settings reads are ~100x faster (no network call or git process per read).
- Time Travel snapshots are serialized per repository and recover from stale git locks.

**WebUI**
- New theme with an accent colour (with a themed colour picker), Solid / Glass / Enhanced materials, and an image **or looping video wallpaper**.
- Floating sidebar that slides away, floating right-hand canvas (Files, Browser, Desktop, Editor, Calendar), chat bubbles, accent-styled buttons and toggles.
- **Recently deleted** chats: deleting a chat moves it to a trash for 30 days, with Undo and Restore.

**Bundled plugins added to the usual set:** Calendar, Personalities, Context Usage, Hardened Terminal Access (disabled by default), and Desktop (live view of your Windows desktop).

## Screenshots

<table>
  <tr>
    <td><a href="docs/screenshots/01-dark-theme-wallpaper.png"><img src="docs/screenshots/01-dark-theme-wallpaper.png" alt="Dark theme with an image wallpaper, Enhanced material and a red accent"></a><br><sub>Dark theme, Enhanced glass over a wallpaper, custom accent</sub></td>
    <td><a href="docs/screenshots/02-light-theme.png"><img src="docs/screenshots/02-light-theme.png" alt="The same screen in the light theme"></a><br><sub>Light theme</sub></td>
  </tr>
  <tr>
    <td><a href="docs/screenshots/03-calendar-canvas.png"><img src="docs/screenshots/03-calendar-canvas.png" alt="Calendar in the floating right-hand canvas"></a><br><sub>Calendar in the floating right-hand canvas (Files, Browser, Desktop, Editor, Calendar)</sub></td>
    <td><a href="docs/screenshots/04-desktop-viewer.png"><img src="docs/screenshots/04-desktop-viewer.png" alt="Desktop viewer panel"></a><br><sub>Desktop viewer: live view of the Windows desktop</sub></td>
  </tr>
  <tr>
    <td><a href="docs/screenshots/05-chat-solid-material.png"><img src="docs/screenshots/05-chat-solid-material.png" alt="Chat with the Solid material"></a><br><sub>Solid material: no blur, fastest</sub></td>
    <td><a href="docs/screenshots/06-enhanced-glass-wallpaper.png"><img src="docs/screenshots/06-enhanced-glass-wallpaper.png" alt="Enhanced glass material over a wallpaper"></a><br><sub>Enhanced glass: the sidebar and chat bubbles frost the wallpaper</sub></td>
  </tr>
</table>

## Requirements

- Windows 10 or 11
- [Python 3.12](https://www.python.org/downloads/windows/)
- [Git](https://git-scm.com/download/win)
- A model: either a local server such as [LM Studio](https://lmstudio.ai/) (the default provider) or an API key for a hosted provider
- Some disk space: the full dependency set (PyTorch via sentence-transformers, Playwright, document parsers) is several GB

## Install

```powershell
git clone https://github.com/JPChoom/agent-zero-windows.git
cd agent-zero-windows
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run it:

```powershell
.\"run Agent-Zero.bat"
```

or directly:

```powershell
.\.venv\Scripts\python.exe run_ui.py
```

The UI opens at <http://localhost:5000> (change it with `WEB_UI_PORT` / `WEB_UI_HOST` in `usr/.env`). Open **Settings > Models** to choose your chat and utility models.

### First run and security

- Keep `WEB_UI_HOST=localhost`; do not expose the server directly to your LAN or the internet.
- Set a UI login in **Settings > External Services > Authentication** before using any tunnel.
- If you use Remote Control (a tunnel), set the allowlist in **Settings > Security** first; anything not listed is refused.
- Run it as a normal (non-administrator) Windows account.
- See [SECURITY_LOCAL_INSTALL.md](SECURITY_LOCAL_INSTALL.md) for more.

### Your data stays local

Everything personal lives in the git-ignored `usr/` folder: chats, memory, settings, `.env`, plugin settings, uploads and your work folder. Nothing from `usr/` is ever part of this repository - keep it that way when you contribute.

## Security model

**There is no sandbox.** Upstream Agent Zero keeps the agent inside a Docker container and reaches the host only through a bridge. This fork removes that layer on purpose: the agent's PowerShell, Python and Node processes run **directly on Windows, with the privileges of the account that started Agent Zero**. It can read, change or delete anything that account can, and use anything that account is signed in to. That is what makes native Windows integration possible, and it is also the main risk.

What that means in practice:

- **Use a dedicated, standard (non-administrator) Windows account**, ideally one without access to your personal files, browser profiles or password manager. Never run it as an administrator.
- **Keep the permission mode on Manual** (the default for every new chat) unless you are watching the agent work. "Bypass permissions" exists for unattended runs; it is password-locked and expires automatically, but while it is on the agent can act without asking.
- **Treat anything the agent reads as untrusted.** Web pages, files and command output can contain instructions aimed at the model. The fork marks outside content as data and has an infection check, but no filter is perfect.
- **Do not expose it to the internet** except through the built-in Remote Control tunnel with the IP allowlist configured and a UI login set.
- **Keep Terminal Access disabled** unless you need it.

The safeguards in this fork - permission modes, the list of denied commands, the infection check, untrusted-content wrapping, the tunnel allowlist, the locked Bypass mode and the kill switch - **reduce risk and catch mistakes. They are defense in depth, not a boundary**, and they cannot contain a determined, manipulated or compromised agent. If you need real isolation, run it in a separate Windows user session, a virtual machine, or use the upstream Docker version instead.

Report vulnerabilities privately through GitHub's *Security > Report a vulnerability*, not in a public issue.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.dev.txt
.\.venv\Scripts\python.exe -m pytest -q tests
```

A few tests cover Linux/Docker-only behavior and are skipped on Windows (see the platform markers in `tests/conftest.py`).

## Project layout

See [AGENTS.md](AGENTS.md) for the architecture, conventions and per-folder contracts. In short: `api/` (HTTP handlers), `helpers/` (shared backend code), `plugins/` (built-in plugins), `webui/` (Alpine.js UI), `prompts/` and `agents/` (agent behavior), `tests/`.

The `docs/` folder is **upstream's documentation**. It is kept for reference, but much of it describes the Docker-based setup and does not apply to this fork.

## Contributing

Issues and pull requests are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md). Please never include chats, secrets, personal paths or other private data in a report or patch.

## Credits and license

Based on [Agent Zero](https://github.com/agent0ai/agent-zero) by Agent Zero, s.r.o. and its community. Licensed under the [MIT License](LICENSE); upstream's copyright notice is kept, with an added notice for this fork's modifications.

Bundled third-party components keep their own licenses, e.g. the toggle-switch style adapted from [chicogale's design on uiverse.io](https://uiverse.io/chicogale/tall-starfish-3) (MIT).
