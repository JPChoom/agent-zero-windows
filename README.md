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
