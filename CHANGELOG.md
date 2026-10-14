# Changelog

All notable changes to Agent Zero for Windows. Versions are git tags (`vX.Y`, or `vX.Y.Z` for patch releases).

## v1.4

A real installer, Agent Zero running its own local model server, long chats that no longer run out of context, and a much tighter permission and security core.

**Behaviour changes:** remote access now needs a sign-in (Remote Control is refused while no login is set), and the llama.cpp provider's default address is `http://127.0.0.1:8090/v1`.

### New
- **llama.cpp server plugin**: Agent Zero starts, watches and stops its own `llama-server.exe`, so LM Studio is no longer required (it keeps working as a provider). Download the official build from the plugin's settings (installed only if its SHA-256 matches the one GitHub publishes), pick a GGUF model, Start. It listens on 127.0.0.1 only, checks that the model you chose is the one loaded, refuses to start when an NVIDIA GPU clearly lacks memory, restarts after a crash, and never leaves a stray server behind. The llama.cpp provider now defaults to it (`http://127.0.0.1:8090/v1`).

### Improved
- **A sentence before a tool call no longer counts as "misformatted"**: replies like "Retrying the read:" followed by a valid call were rejected, and the agent gave up after six tries. One announcing sentence before a single, final tool call is now accepted.
- **"Lock is bound to a different event loop" error fixed**: the skills prompt (and workdir/prompt-include scans) shared one lock across all agents; a background agent running on another event loop broke it. Each loop now has its own.
- **Calendar showed scheduled tasks an hour early after a clock change**: a daily 6 am task appeared at 5 am from November to March. The calendar carried October's UTC offset forward; it now re-applies the zone's real offset at each date. The same re-pin is used by the "is it due" check.
- **Utility model no longer thinks on LM Studio**: memorizing, titles and summaries made a reasoning model think for minutes and hit the 180 s utility timeout ("Memorize solutions extension error"). Utility calls now ask LM Studio for no reasoning (a 33 s call took 4 s); set `reasoning_effort` in the Utility slot kwargs to override.
- **Time Travel no longer times out on big workdirs**: files over 20 MB are skipped and staging gets 180 s instead of 20 s (a 9 GB workdir made every automatic snapshot fail).
- **Tool calls with an unclosed `thoughts` list are accepted**: a model that forgot the closing bracket made every tool call unparseable, and the agent stopped after six identical retries. The list is now closed automatically when that is the only fault.
- **Vision sidecar now works**: with a text-only Main model and a sidecar model configured, the agent was never told that `vision_load` exists, so it never used the sidecar (it probed the terminal for image tools instead). It now learns the tool, and that the sidecar describes images for it.
- **Local models no longer time out on a Docker-era address**: provider defaults (and what the onboarding wizard saved) use `host.docker.internal`, which natively resolves to the PC's network address, where LM Studio (listening on 127.0.0.1 only) never answers. Such addresses now reach this PC through loopback. This affected any slot whose address was left blank, such as the vision sidecar and embeddings.
- The infection check's "Safety check: your decision needed" card now has the same styled Allow / Block buttons as the permission and safety-policy cards (they were plain text), and a test keeps any new approval card from shipping unstyled.
- **Long chats no longer die on "Context size has been exceeded"**: Agent Zero now uses the context window the local server actually loaded (LM Studio and llama.cpp report it; LM Studio can reload a model with a smaller window than you configured), trims recalled memories, matched skills and file listings for a turn when they leave too little room, and on an overflow compresses, shrinks its working window and retries with a short note instead of failing and filling the history with the error text.
- **AgentZero.exe and Uninstall.exe**: the installed app starts from `AgentZero.exe` (a native launcher with the tray icon, so Task Manager and the taskbar show its name), and `Uninstall.exe` (also in *Settings > Apps*) removes the program and asks whether to keep your data. Another copy's shortcuts are never touched.
- **Setup .exe** (`AgentZeroWindows-Setup.exe`, built from `installer\cmd\setup`): one file to download and run. Setup offers a desktop shortcut and can also download the llama.cpp server (CUDA, Vulkan, AMD ROCm or CPU build, verified before it is installed).
- **Installer** (`installer\install.ps1`, Windows 11, per user, no admin rights): installs a release with the exact tested package versions (`requirements.lock.txt`), adds a Start menu entry with a tray icon (Open / Settings / Quit) and a *Settings > Apps* entry. Uninstalling keeps your data unless you choose a clean uninstall.
- **Windows workflow benchmark** (`tests/manual/windows_workflow_benchmark.py`): realistic Windows tasks (file edits, CSV, organizing, a Windows query, recovering from a read-only file, a sub-agent, a refused persistence request, optionally Notepad) run by the real agent and scored on what actually happened, with interventions and unintended effects. It is the yardstick for future changes, including the experimental dynamic sampling.
- **Models**: *Use the Main model for all slots* (single-model mode) and **Sampling** settings (temperature, top P, top K, repeat penalty; each can be locked) in *Settings > Agent > Models*. An **Experimental**, off-by-default dynamic adjustment nudges the unlocked values per call (more focused while coding, more varied for creative writing); it asks before turning on and has no measured benefit yet.
- **Agent Workspace**: every app keeps a history of which agent controlled it (hover its name in the Workspace view), every ownership change is in the access log, and a hand-over can no longer overwrite an owner change that happened a moment earlier.

### Security
- Remote (tunnel) access is refused while no WebUI login is set, even from an allowlisted address, and Remote Control cannot be started without one: without a login nothing asks for authentication.
- WebSocket connections that are not signed in are refused at connect, before they are registered or see any server or connection details.
- The `input` tool, which types into the same terminal as `code_execution_tool`, now passes the command safety floor too. Before, a denied command sent through it ran unchecked in Auto or Bypass mode.
- The kill switch now stops every tool that acts (browser, file edits, MCP tools, remote execution, scheduler...), not only the terminal and Computer Use; read-only tools keep working so the agent can still explain. Remote execution on a CLI-connected machine also passes the command safety floor.
- Parallel jobs follow their chat's permission mode and messaging cap (they ran at the default mode), and their approval requests now appear in that chat instead of timing out unseen. Scheduled tasks created or changed from a Telegram, WhatsApp, Email, Discord or Slack chat run under that channel's cap.
- The permission gate fails closed: if its settings cannot be read it decides as Manual mode (reads run, edits and commands ask) instead of letting every tool run, and an invalid messaging-channel cap counts as Manual instead of Auto.
- A plugin, project or `usr/` folder can no longer replace a security gate (kill switch, safety floor, permission gate, secret guard, infection check...) by shipping an extension file with the same name; such a file is ignored with a warning.
- Computer Use `launch` only starts applications; scripts, shortcuts and installers must go through the terminal tool, where the command safety checks apply.
- The file editor never writes to a Startup folder, whatever its access setting.
- Remote Computer Use (through the CLI) refuses the key combos A0W blocks locally (lock, sign out, Ctrl+Alt+Del, Run dialog...) and stops while the kill switch is on.
- When the coding completion gate is on, running a project's own build and test commands follows the chat's permission mode (Plan never, Manual and Accept-edits ask once per project, Auto runs); they used to run unasked.
- The session cookie is marked Secure when you come in over the HTTPS tunnel.
- The WebSocket test harness and event console (Settings > Developer) are off unless `A0_DEV_HARNESS=1` is set in `usr/.env`; the event console could show other sessions' WebSocket traffic.
- Every HTTP endpoint that skips the CSRF check is now listed and justified in a test, so a new exemption cannot slip in unreviewed.
- Docs and Settings say plainly that the File Browser access setting limits the File Browser and Editor, not what the agent's terminal can reach.
- When requests from an address not on the allowlist look like an already signed-in Agent Zero page (its regular background calls), the notification says so and asks whether it is you on another network, instead of a generic "blocked" warning.
- Telegram webhook mode always uses a secret (a random one when none is configured), and updates without the matching secret are refused.
- The access log stores header values only for a list of known-safe headers; any other header (for example a custom one carrying a token) is recorded as present only. Secret-looking query values in the referer are redacted too.

## v1.3

A Windows Explorer-style File Browser, the Agent Workspace, and a faster, lighter Desktop view.

### New
- **File Browser rebuilt** as a Windows Explorer-style browser (address bar, Quick access, drives, sorting, multi-select, shortcuts, cut/copy/paste, drag-and-drop upload of files and folders, drag-out download, previews, built-in text editor, Recycle Bin deletes, ZIP downloads). *Settings > Security* chooses what it may open (Agent Zero user folder, Agent Zero folder, or the whole Windows drive; other and removable drives separately; a stricter limit for remote sessions); Agent Zero's own secrets are never shown. The old work-dir file endpoints were removed.
- **Agent Workspace**: a Workspace view of which agent owns which apps, terminals and browser tabs, with Adopt / Release / Close and an owner picker. Inside a chat, ownership follows the agent chain: an agent may use its own and its sub-agents' apps without asking, but must be handed (`computer_use` `hand_over`) or ask before using a superior's. A replaced sub-agent's apps pass up; a parallel job's apps go back to the agent that started it. Browser tabs show which agent opened them.

### Fixed
- An app a parallel agent launched through Computer Use was forgotten when the job ended, so the chat that started the job could not close it or type into it without an approval, and nothing listed it. Apps now pass to that chat; deleted chats leave their apps listed as orphans (never closed automatically).
- App ownership is checked against the process's start time, so a reused process id can never make the agent "own" an unrelated program.
- Terminal sessions now end when their chat is deleted or reset, when a parallel worker finishes, and when a sub-agent is replaced, instead of whenever garbage collection ran.
- The main Settings save can no longer change the File Browser access settings, and every Bypass-password check shares one wrong-attempt limit.
- Only one Desktop icon in the side rail on Windows (the Linux desktop surface was always registered as well).
- The Editor can open, save and Save As any file the File Browser may open (same *Settings > Security* policy, stricter for remote sessions), instead of failing outside the workdir and projects.
- Local times in the access log and the server log file names are correct on Windows (they were an hour ahead of UTC instead of local time when a timezone was set).
- A page that loses access (expired session, blocked address, restart) backs off instead of retrying background requests every few seconds.

### Changed
- Desktop viewers share one capture loop, unchanged frames are not re-sent, and an idle screen is captured about once a second (full speed returns on any change or input).

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
