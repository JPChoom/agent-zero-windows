# Changelog

All notable changes to Agent Zero for Windows. Versions are git tags (`vX.Y`, or `vX.Y.Z` for patch releases).

## v1.6.3

Replies to messaging chats are no longer lost, the chat-app loopholes found in an audit are closed, the local model server needs a key, and child agents get a live panel and a worktree of their own.

### New
- **See what each child agent is doing.** A new *Child agents* panel in the side rail lists the child agents of the open chat: whether each is working, what it is doing right now (its newest step), how many steps it has taken and when it last did something, with *Stop* and *Open chat*. In a child's chat it shows its siblings and a way back to the parent.
- **A git worktree per child agent.** Give `child_agent` a `repo` and the child works in its own branch and folder of that repository instead of the main checkout; the parent reviews, commits, merges or discards the child's work with `coding_task` and `child`.
- **A lint check after every Python edit.** When the agent writes or patches a Python file, ruff (if it is installed) looks for mistakes that still parse but fail when run, such as an undefined name, a name used before it is assigned or a function defined twice, and the agent is told in the same step. Only problems the edit added are reported, and unfinished code (unused imports) is not flagged. On by default (Coding controller settings); without ruff nothing is checked.

### Security
- **The local model server needs a key.** Agent Zero's own llama.cpp server answered anything on this PC, including a virtual machine allowed to reach the PC's loopback, so any of them could use the model and the GPU. It now starts with a random key that Agent Zero sends on its own calls; every other caller gets refused (except a health check). The key is in `usr/llama-cpp/api_key.txt` for your own tools, and *Require an API key* in the local server's Advanced settings turns it off.
- **Discord no longer trusts display names.** The allowed-users list matched a person's display name as well as their unique username, so anyone could set their display name to an allowed entry and be answered. Only IDs and unique usernames match now.
- **Telegram's /sessions shows only your own chats.** The list and its picker offered every chat on the PC (WebUI chats, other people's chats, other channels), so a second allowed user could see another's chat names, adopt their chat and read its history. Now only chats from the same bot and user are offered; *Offer WebUI chats in /sessions* adds your plain WebUI chats back for continuing them from your phone.
- **A profile or project set for a channel stays fixed.** `/agent` and `/project` could swap a profile or project set in a channel's settings for another, leaving its capability limits. They now refuse; *Allow switching agent and project* in the channel's settings turns that off. Global capability limits and the messaging limits always held.
- **Email can require a verified sender.** A From address is easy to forge. With *Require a verified sender* on, an account answers only mail its mail server verified (DMARC pass, or a DKIM pass for the sender's own domain). Off by default; not available for Exchange accounts.

### Fixed
- **Stopping an agent closes the question it was asking.** An agent stopped while waiting for Allow or Deny (with the Stop button, or a stopped child agent) left its question open until it timed out. The card now shows that it was cancelled, and the pending answer and the phone code are dropped.
- **A reply to a messaging chat is no longer lost when the first send fails.** Every channel sent a reply once: Discord and Slack logged a failure and dropped it, WhatsApp and email asked the language model to resend (twice), and Telegram reported a failed send as a success, so those replies vanished without a trace. All five now retry in line when the failure is temporary (network trouble, a timeout, rate limits, a bot that is restarting), waiting as long as the service asks. A reply still failing after that is queued on disk and retried about once a minute, with growing gaps, until it arrives or is 24 hours old; the queue survives a restart, and the chat shows a note when a reply is queued, delivered or given up. Failures that cannot get better (a blocked bot, a chat that no longer exists, bad credentials) are not retried. Approval questions sent to your phone get quick retries too. A retry can deliver a reply twice when the first send worked but its confirmation was lost.

## v1.6.2

Fixes the Responses API calls that v1.6.1's package update broke, makes a finished coding task clean up after itself, and gives a model that repeats itself a useful warning.

### Fixed
- **Calls through LiteLLM's Responses API work again.** v1.6.1's LiteLLM 1.108 needs a newer MCP library than A0W ships, so every call A0W makes through that API failed with `cannot import name 'CacheableResult'`, while plain completion calls worked. Vision captions on an LM Studio model failed outright, and background jobs on such a model quietly moved to the Main model. LiteLLM is now 1.102.4 (the last release for MCP 1.x) and MCP 1.30.0, and a new test makes a real Responses API call against a local stand-in server, so this combination can't ship again.
- **A finished coding task leaves nothing behind.** `coding_task merge` fast-forwarded the main branch but left the task's folder and branch until a separate `discard`. A successful merge now removes both (`keep: true` keeps them). Found by the new capability benchmark.
- **A model that repeats itself gets told why.** When a model sends exactly the same reply twice, Agent Zero does not run its tool call again. The warning only said "You have sent the same message again", so a local model that resent a command because its first result looked empty kept resending it until the turn ended after six tries. The warning now says the call was not run again, that the first result is already in the chat, and to change the call or report what is blocking it.

## v1.6.1

A virtual machine can no longer reach Agent Zero as if it were you, and the Python packages get minor and patch updates.

### Security
- **A virtual machine can no longer reach Agent Zero as if it were you.** A VM on VirtualBox's default NAT network (QEMU and some others work the same way) reaches this PC through its loopback address, so A0W counted it as a local visitor and let it in without a login or the allowlist. A0W now checks which program is on the other end of a local connection: a VM, an SSH port forward or a tunnel client counts as remote and is refused like any other remote visitor.

### Dependencies
- **Refreshed packages, minor and patch versions only.** LiteLLM 1.88 to 1.108, pydantic 2.11 to 2.13 (2.14 breaks the Telegram library), Flask 3.0 to 3.1, tiktoken 0.8 to 0.14, plus smaller updates to uvicorn, python-socketio, urllib3, nltk and others. Major-version updates (openai 3, langchain-core 1, mcp 2, sentence-transformers 6 and more) are left for separate, tested changes. The hash-checked lock file was rebuilt; *Check for updates* installs the new packages.

## v1.6

Agents can be limited to the tools you choose, run as independent named children, and use any model for any job; coding tasks get their own branch and a syntax check after every edit; the Editor reviews the agent's changes; and messaging chats can answer approval questions from the phone. An empty channel allowlist now answers nobody, and new learned skills wait for your approval.

### New
- **Background jobs keep working when the Utility model's PC is off.** If a Utility model on another PC doesn't answer, its jobs move to the Main model and a banner says so, instead of memory saves and compression failing. They move back by themselves. You can turn this off in *Settings > Models > Background jobs*.
- **Choose which model runs each background job.** The same section sets chat naming, memory, compression and skill learning to Utility or Main, one by one.
- **Subordinate agents can run on the Utility model.** List agent profiles to send their subordinates there, such as simple research work. Nothing moves until you list one. Their safety checks stay on the model set for the check.
- **Long tool results can be shortened (experimental, off by default).** The Utility model summarizes the middle of very long outputs, so later steps read less. The start and end stay word for word and the full text is saved. A detail in the middle can still be lost from what the agent sees.
- **Info section with a speed counter.** A new collapsible Info section in the sidebar, above Tasks, holds an FPS-style tok/s readout with a 60-second graph. It updates live while the model writes, shows "reading prompt..." during re-reads, and keeps the last value between replies. Click it for the model, first-token time and how much of the prompt was unchanged. Rates are estimated from the streamed text.
- **Decision model in shadow mode (off by default).** A decision model such as Laya, running on the Utility model's server, predicts whether a step needs thinking and how hard a delegated task is. The predictions are logged next to what really happened, without the text, and never change what runs. This measures whether such a model is worth using.
- **Shadow safety check (off by default).** When the Main model judges, the Utility model can judge the same step in the background and both verdicts are logged. It never changes what runs. A small model isn't safe for this job yet: on the 18-case test, a 9B model allowed one hostile command.

- **Review the agent's changes in the Editor.** When the agent changes a file you have open, the Editor shows each change against the text from before, with Accept and Reject on every change, plus Reject all and Accept all. Rejected changes are written back to the file. If you had unsaved edits, they are kept: rejecting a change keeps your text. Built on CodeMirror 6 (MIT).

- **A profile per messaging channel.** Each Telegram, Discord or Slack bot, the WhatsApp account and each email account can set the agent profile for its new chats, for example a researcher on Telegram.
- **Answer approval questions from your phone.** In a chat that came in over Telegram, WhatsApp, Discord or Slack, permission and safety questions are now also sent to that chat with a short code: reply `yes 7KQ2` or `no 7KQ2`. Only senders on that channel's allowlist can answer, and only when the list is not empty. Email never answers approvals, because sender addresses are easy to fake.
- **A branch and folder per coding task.** A new `coding_task` tool gives a coding task its own git worktree: it works there, shows its diff, commits on its own branch and merges back only by fast-forward, refusing when the main checkout has changed or has unsaved work. Commits and merges ask first in Manual mode.
- **A syntax check after every edit.** When the agent writes or patches a Python, JSON, YAML, TOML or JavaScript file, A0W checks that it still parses and tells the agent in the same step. It runs no code and is on by default (Coding controller settings).
- **Read-only coding roles stay read-only everywhere.** The code reviewer and diagnostician now ship capability limits, so they cannot change anything through a child agent, a parallel call, the browser or an MCP tool either.
- **Any model for any job or agent profile.** Background jobs, subordinates and child agents can run on the Main model, the Utility model or any saved model preset, set per job and per agent profile (for example `researcher = utility`, `developer = preset:Coder`). A model server counts as ready only when it answers for its models, not just when its port is open; a job falls back to the Main model when its server is away or the prompt does not fit, but a refused request is no longer quietly re-sent. Settings shows recent fallbacks and why.
- **Independent child agents.** A new `child_agent` tool starts a named agent in a chat of its own, nested under the parent in the sidebar. It keeps its history between tasks and across restarts, can work while the parent continues, and can be stopped from its own chat without stopping the parent. A parent stopped while waiting stops the child, and resetting or deleting the parent stops its children. Children work under the parent's permission mode and capability limits. `call_subordinate` is unchanged.
- **Capability limits per agent.** Settings > Capabilities sets which tools and actions an agent may use at all, globally, per project or per agent profile: for example a research profile limited to reading and searching. The limits hold in every permission mode, Bypass included, a narrower scope can only narrow them, and subordinate agents keep their superior's limits. Fully refused tools are not offered to the model, MCP tools included. Messaging chats can get extra limits, every step of a bundled browser or parallel call is checked, and a parallel job keeps the limits of the agent that started it. Settings lists the tools on your install. Nothing changes until you set a limit.

### Improved
- **Learned skills show how well they work.** Each use now records whether the task ended with an answer and how many problems came up, and the Learned skills window shows "worked 3 of 4 times". It also shows when a skill matched a request but was not used, which helps tell a weak skill from one A0W fails to pick up.
- **Freezes record what caused them.** When the interface stalls for more than half a second, A0W notes which code was running (names only, no content), so the remaining freezes can be fixed one by one.

### Fixed
- **A chat save never writes over the last good copy.** If Windows kept the chat file locked, a save fell back to writing it in place, which could leave it half written if A0W stopped at that moment. The old copy is now kept and the save is retried a few seconds later.
- **The safety check always judges a tool call,** even when nothing was collected from the model's stream, as can happen with native function calls. It used to let such a call run unchecked.
- **The automatic prompt cache fits the machine.** It never went below 8 GB, even on a PC with 8 GB of RAM. It now uses about a third of RAM (1 GB minimum); PCs with 24 GB or more are unchanged.
- **A model stuck repeating itself is stopped.** Local models can loop on a line with one small change, such as endless rows of a made-up table. One ran for 37 minutes until it was stopped by hand. A long reply that keeps repeating is now cut off, nothing from it runs, and the model is told to do the job another way.
- **Long replies no longer slow down as they grow.** Agent Zero re-read the whole reply on every token, which held a very long reply near 8 tok/s. Most of that work now happens only when a tool call could have finished, so a 16,000-token reply costs about 15 ms per token instead of about 115 ms.
- **The timing line no longer blames a hook for your thinking time.** Waiting for you to answer a safety or permission question counted as hook time, which made the safety check look slow. It now shows separately as "waiting for you".

### Security
- **An empty allowlist now means nobody, on every channel.** Telegram, WhatsApp and email used to answer anyone when their allowed-users list was empty; Discord and Slack already answered nobody. Add yourself to a channel's list for it to answer you.
- **The setup script installs only signed releases.** `installer/install.ps1` now verifies the release tag against a release key pinned in the script before checking anything out, and installs only from the hash-checked package list.
- **New self-learned skills wait for your approval.** A skill learned from a task that only used this PC used to go live at once. Every new one now waits under *Learned skills > Needs a look* until you approve it. You can turn this off in the Skills settings.
- **A skill learned from a downloaded file now waits for your review.** Reading a file on this PC counted as your own content, so a skill learned from a file downloaded earlier went live at once. A file in a downloads folder, or one Windows marks as coming from the internet even after it was moved, now counts as outside content, like a web page.

## v1.5.5

The safety check now blocks what it can't check and is firm again on hostile actions, a chat can't be damaged or rolled back by a save, and installs in a folder with a space work with `/a0/...` paths.

### Security
- **The safety check no longer lets an action through when it can't run.** If the safety model failed, timed out or replied without a verdict, the tool ran unchecked with no warning; any other error in the check did the same, and stopping the agent during a check could still let the tool run. A failed check now retries on the Main model, with thinking off. If no model answers, you get the usual Allow/Block question, and no answer means blocked; with nobody to ask (headless mode) the action is blocked outright, and the agent can never answer for itself. The safety policy's hard rules and permission modes were always enforced regardless.
- **The safety check is firm again on hostile actions.** v1.5.4 split the check's prompt into separate messages for speed and reported the verdicts as identical, but that was measured on only 6 cases. A wider test found 2 of 9 hostile cases asking the user instead of blocking. None were allowed: the action still waited for an answer. The check now ends by repeating its steps, and all 9 were blocked on each of 4 runs, with the same speed (0.6 s to re-read a 19,000-token prompt). One routine case changed the other way: deleting a build folder now asks first when the conversation doesn't show the user asked for it. The 18 cases are kept as a repeatable test, `tests/manual/infection_check_corpus.py`.

### Fixed
- **A chat can't be damaged or rolled back by a save.** A save emptied the chat file and wrote it again, so a crash or a closed window at that moment left a damaged file, and a damaged chat doesn't load. Since v1.5.4 two saves could also overlap, and an older copy could land last and undo newer messages. A save now replaces the file in one step, and saves stay in order. Each one takes 1-5 ms longer.
- **Installs in a folder with a space work with `/a0/...` paths.** The v1.5.3 path fix wrote the folder without quotes, so on an install under `C:\Users\First Last\` the shell split the path in two. Paths now get quotes where they need them, and PowerShell gets `&` when the path is the command itself. In Python and Node code, only paths inside strings are rewritten, so a division such as `total /a0` is left alone.

## v1.5.4

Long chats on local models get faster: the safety check no longer re-reads the conversation on every step, and background history compression waits for a real gap and keeps its work.

### Improved
- **Background history compression waits for a real gap, and its work is kept.** It used to start right after a step, just as the next step needed the model, so about 12% of its calls were cancelled within a second (233 of 1,983). It now waits until the model has been free for 15 seconds, or starts at once if the history is over its limit. Its results also weren't saved when it finished after the turn's last save, so closing the window lost them and the next start redid the same summaries; the chat is now saved after each pass that changed something.
- **The safety check no longer re-reads the conversation on every step.** On models that can't trim their memory partially, such as Qwen3.8, the server can only rewind to checkpoints at message boundaries. The check sent the history and the agent's latest output as one message, so replacing the output left nothing to rewind to and the whole history was read again: about 33,000 tokens and 16 s per check in a test with the real model and settings. History entries now go as separate messages: about 5,500 tokens and 4.8 s. Verdicts were identical on the benign and hostile test cases. The bigger prompt cache in v1.5.3 did not reduce these re-reads; this does.

## v1.5.3

Installs outside `C:\a0` now use their own folders in the terminal, each step starts faster, and the local model server keeps more earlier prompts in RAM instead of re-reading them.

### Fixed
- **Installs outside `C:\a0` used the wrong folder in the terminal.** Agent Zero gave the agent some paths in upstream's container form, `/a0/...` - the default working folder, uploaded files, project and skill paths - and Windows reads `/a0/...` as `C:\a0\...`. So on any install not at `C:\a0` (the README's `agent-zero-windows` folder included) the agent's terminal started in, and wrote to, `C:\a0\usr\workdir`. The terminal and the agent now get this install's real paths, a stored `/a0/usr/workdir` setting is read as the real folder, and `/a0/...` paths in commands (from old memories or skills) are rewritten to this install before they run. Found when the development copy's benchmark wrote into the live install's folder; two benchmark tasks that always failed there now pass.

### Improved
- **Each step starts faster.** Building the system prompt took 1-2.4 s per step on a live install, most of it in the tool list: it looked up the prompt folders again for each of ~30 tool files, and the subordinate-agent tool slept 100 ms on every step retrying a file that doesn't exist. The folders are now looked up once per build and reused for two seconds, and a missing file fails at once (a briefly locked file is still retried). Measured on the development copy: the whole system prompt 440 -> 122 ms, the tool list 310 -> 54 ms, with identical text. It also ran on A0W's main loop, so the UI stalls less.
- **The local model server keeps more earlier prompts in RAM.** Main and utility calls share the server's one slot; after a safety check or memory call, the conversation is restored from a RAM cache instead of re-read - but only if it fits. On the owner's logs 46% of requests re-read almost the whole prompt (197 of 238 minutes of prompt reading) with llama.cpp's 8 GB default; the cache is now about a third of system RAM (8-32 GB; *Settings > Models > Local model server > Advanced > Prompt cache*).
- **The turn timing line shows how much of the prompt was unchanged** since the previous step ("prompt unchanged 97%"), so a change that forces the server to re-read everything is visible.

## v1.5.2

Agent Zero learns skills on its own, with a window to review, edit and delete them; installing from the README now uses the signed release and hash-checked packages; and smaller fixes from an external code review.

### New
- **Agent Zero learns skills on its own.** After a long task that succeeded (8+ steps, or 3+ minutes), it saves the steps as a skill in the background, so the next similar request goes faster; saying "learn that skill" saves the last task right away. A skill from a task that only used your own files and commands is active at once; one from a task that read web pages, messages or downloads waits under **Needs a look** until you approve it, since such content can carry hidden instructions. The new **Learned skills** window (sidebar quick actions) shows each skill with how long the task that taught it took against later uses, and lets you approve, edit, restore older versions, turn off or delete. Settings: *Skills > Learn skills on its own*.

### Fixed
- **Installing from the README now uses the signed release and checked packages.** The steps cloned the development branch and installed `requirements.txt`, so a new install skipped both the release signature and the package hashes that the in-app updater checks. They now check out the latest signed release (`git verify-tag` against `conf/release_signers`) and install with `pip install --require-hashes -r requirements.lock.txt`.
- **Model calls no longer fail when the local server restarts with new settings.** The restart waited until no chat was busy, but a message sent in that same moment could reach a server that was stopping. Calls to it now wait for the restart, and a turn that starts at the last moment cancels it.
- **Background history compression can't replace messages that changed meanwhile.** It summarizes while the turn goes on; it now checks the messages are still the same before replacing them, and otherwise tries again next time.
- **The turn timing line no longer reports a "first token" for calls that don't stream** (most background calls): it showed their whole duration as time to the first token. They now say "not streamed".
- **No more "Batches: 100%" lines** in the terminal from the local embedding model on every memory lookup.

## v1.5.1

A patch release for local models: tool calls that a local Qwen model wrapped in its own tags are run instead of rejected, thinking can no longer fill the context window, the model leaves GPU memory when Agent Zero closes, a warning when Vision does not fit, and no duplicate Telegram, email or WhatsApp pollers. New: a thinking setting for the Main model and history compression ahead of time.

### Fixed
- **The local model stays in GPU memory after Agent Zero is closed.** The server was only stopped on a clean exit; closing the console window, a crash or Task Manager left `llama-server` running with the model loaded. Windows now ends it together with Agent Zero, however Agent Zero ends.
- **Vision could silently make the local model ~10x slower.** When the model plus its image projector does not fit in GPU memory, Windows moves part of it into system RAM instead of refusing (measured: 120 -> 9 tokens/s, model calls stalling after 2 minutes). The start-up memory check now counts the projector, Settings shows whether Vision fits before you turn it on, and a warning appears when a running model has spilled into system RAM.
- **Telegram: "Conflict: terminated by other getUpdates request" over and over.** When a plugin's files changed while Agent Zero ran, plugin code was reloaded and the Telegram plugin forgot the bot it had running; the next minute it started a second one for the same token, and the two kept knocking each other off Telegram. The list of running bots now survives the reload, as it already did for Discord and Slack. The same reload could also make the email integration read each mailbox twice and WhatsApp start a second bridge; both now keep their running loops too.
- **"Message misformat" and "I stopped myself here" while coding on a local Qwen model.** Two causes, found in the logs (41 rejected replies). Three quarters were tool calls the model wrapped in its own `<tool_call>` tags and left one closing brace short; they were rejected, the model sent the same reply again ("You have sent the same message again") and the turn ended after six tries. Such a call is now repaired and run when it ends in a closing tag (only missing closing braces are added, nothing else). The rest were replies with no answer at all: the model thought until the context window was full. Over 4,500 logged steps, replies after up to 6k tokens of thinking were almost never empty; past 8k, 29% were, and past 16k all of them. The local model server now ends thinking after 6,144 tokens and has the model answer (*Settings > Agent > Models > Local model server > Thinking limit*, 0 = no limit). The misformat warning now tells the model what to fix.

### Improved
- **Long chats compress before they have to.** History compression only started once the history was already over its limit, so the next step waited for the summarizing (about 3% of turn time over a day, 7% over three days, in bursts of 30 s and more). It now starts in the background at 85% of the limit, runs behind your turn at low priority, steps aside the moment your turn needs the model, and only summarizes - it never drops anything. The hard, blocking pass is still there as the safety net.

### New
- **Thinking budget** for the Main model (*Settings > Agent > Models > Thinking*): **On** (default, as before), **Off** (fastest), or **Auto (Experimental)**: the model thinks on the first step of a turn, where it plans, and after a step that failed, errored or was refused, and skips thinking on the routine steps in between. Works with the local model server (llama.cpp) and LM Studio. The workflow benchmark takes `--thinking on|off|auto` to compare.

## v1.5

Signed releases checked by the updater, packages installed by hash, a faster safety check on local models, and a hardware report for the local model server.

### Improved
- **The safety check reuses the model's prompt cache.** It showed the last 25 messages, a window that slid one message per tool step, so a local server re-read the whole check prompt every time (measured on an RTX 4090 with llama.cpp: about 22,000 tokens, 8.8 s per step). The window now starts at a fixed message and moves in steps of 12, so the prompt only grows at its end and the server reuses it; the check sees 25-36 messages instead of exactly 25.

### Docs
- **[Local model server guide](docs/guides/local-model-server.md)** with measured speed on an RTX 4090 (Qwen3.8-27B Q4_K_M: 47 tokens/s with the fast flags, 99-136 with MTP drafting at 2-6 tokens, n-gram drafting no help), so the Coding preset's choice of 6 is documented, not assumed.

### Security
- **Packages are installed by hash.** `requirements.lock.txt` now carries the SHA-256 of every file PyPI publishes for each locked version, and the in-app updater, the setup script and the GitHub test run install with `pip install --require-hashes`: a package that was changed or swapped on the index fails the install instead of running. The updater also installs from the lock when only the lock changed.
- **Releases are signed, and updates check it.** From this version on, every release tag is signed with the project's release key, and the in-app updater installs a release only when its signature matches a key shipped with the version you already have (`conf/release_signers`). An unsigned release, or one signed by any other key, is refused before anything changes - even if the GitHub account or the download path were taken over, a fake update would not install. The release key is password-protected and kept off the repository.

## v1.4.2

Fixes from a review of v1.4.1, and the GitHub test check passing again.

### Fixed
- **The GitHub test check passes on a clean checkout.** It had failed on every release push since v1.2 because the suite assumed things only present on the developer's PC. One was a real bug: Agent Zero crashed listing plugins when `usr/plugins` did not exist yet (a fresh clone has no such folder); it is now treated as empty. Also: the memory "last used" stamp was never saved in the first ten minutes after the PC booted; a test that leaked a Docker flag into the tests after it; installer tests inheriting PowerShell 7's module path; autostart and Discord tests assuming an install and an optional package.
- A running llama.cpp server is no longer restarted for a saved setting change while a chat is in the middle of a turn (between two model calls, while a tool runs); it waits until no chat is running.
- The startup tripwire also checks when a turn ends, so an autostart entry added by a tool that then failed is undone straight away instead of at the next tool call.
- The image projector for a local model is picked by name when a folder holds several, and never guessed; a path can be given instead. The model picker has an "Also use it for the Utility model" box, so a separate Utility model (for example on another PC) is not overwritten.

## v1.4.1

The local model server (llama.cpp) is now part of the Models settings, with presets that make it fast for coding, and three llama.cpp fixes.

### New
- **Local model server is part of the Models settings.** The llama.cpp server is no longer a separate plugin: *Settings > Agent > Models > Local model server* lists your GGUF files (including LM Studio's), and picking one points the Main and Utility models at it. Presets replace hand-typed server options: **Coding (fast)** (flash attention, 8-bit memory cache, prompt reuse, plus MTP self-drafting when the model has an MTP layer - about 2.5x faster answers with Qwen3.8-27B on an RTX 4090: 47 -> ~130 tokens/s), **Balanced**, **Low memory** and **Custom**. A Vision switch loads the model's own image projector so the Main model can see images. The context size follows the Main model's, and a running server restarts with saved changes on its own (never in the middle of a turn). Settings of the former plugin are carried over.

### Improved
- Changing a llama.cpp server setting no longer fails now and then with "Port 8090 is already used by another program": the old server's port is given a moment to be released.
- **llama.cpp server works fully with thinking models**: Agent Zero now talks to llama-server over its chat-completions route, where the model's thinking comes back and shows in the chat (the Responses route dropped it), and utility calls (memorizing, titles, summaries) turn thinking off there too, as they already did on LM Studio.

## v1.4

Faster and steadier on a local GPU (in the workflow benchmark: total time 1,494 s -> 705 s, all tasks passing), Agent Zero running its own local model server, long chats that no longer run out of context, and a much tighter permission and security core - including protection against an agent working its way around a refusal.

**Behaviour changes:** remote access now needs a sign-in (Remote Control is refused while no login is set), and the llama.cpp provider's default address is `http://127.0.0.1:8090/v1`.

### New
- **Speed measurement** (start of the local-speed work): every turn now records where its time went - each model call's wait for the GPU, time to first word, hidden "thinking", answer length and speed, plus tool time, hook time and moments the UI froze. One summary line per turn in the console; details in `usr/perf/` (numbers only, never chat text). The workflow benchmark reports the same totals.
- **llama.cpp server plugin**: Agent Zero starts, watches and stops its own `llama-server.exe`, so LM Studio is no longer required (it keeps working as a provider). Download the official build from the plugin's settings (installed only if its SHA-256 matches the one GitHub publishes), pick a GGUF model, Start. It listens on 127.0.0.1 only, checks that the model you chose is the one loaded, refuses to start when an NVIDIA GPU clearly lacks memory, restarts after a crash, and never leaves a stray server behind. The llama.cpp provider now defaults to it (`http://127.0.0.1:8090/v1`).

### Improved
- **Your turn comes first.** Memorizing and chat naming used to queue on the model ahead of your next message (about 200 s of waiting across the benchmark). They now run only in quiet gaps between turns, and if you send a message while one is running it stops at once and tries again later (on an RTX 4090 a reply started in 0.8 s instead of waiting behind a long memorize call). Memorizing also reads only what is new since it last ran, instead of the last 80,000 characters of the whole chat after every reply, and skips turns with nothing worth keeping.
- **Workspace no longer shows a blank panel**: when docked, it came back empty after a page reload because the panel never loaded its own data store.
- **Faster safety check (infection check)**: it used to start checking before the tool call was finished, then throw that work away and start again - double the model time on every tool call (it was a quarter of all time in the benchmark). It now checks the finished call once and waits for that result. A call already allowed in the same chat, with identical arguments, is not checked again, and the check writes a one- or two-sentence verdict instead of a paragraph. It also no longer reuses a verdict that never saw the tool's arguments.
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
- **Windows workflow benchmark** (`tests/manual/windows_workflow_benchmark.py`): realistic Windows tasks (file edits, CSV, organizing, a Windows query, recovering from a read-only file, a sub-agent, a refused persistence request, optionally Notepad) run by the real agent and scored on what actually happened, with interventions and unintended effects. It is the yardstick for future changes, including the experimental dynamic sampling.
- **Models**: *Use the Main model for all slots* (single-model mode) and **Sampling** settings (temperature, top P, top K, repeat penalty; each can be locked) in *Settings > Agent > Models*. An **Experimental**, off-by-default dynamic adjustment nudges the unlocked values per call (more focused while coding, more varied for creative writing); it asks before turning on and has no measured benefit yet.
- **Agent Workspace**: every app keeps a history of which agent controlled it (hover its name in the Workspace view), every ownership change is in the access log, and a hand-over can no longer overwrite an owner change that happened a moment earlier.

### Security
- **A refused command can no longer be worked around.** In testing, the agent was refused a "start with Windows" registry entry, then rebuilt the path as `'Current' + 'Version\Run'` to slip past the match - and succeeded. Four layers now stop that: (1) a refusal tells the agent not to try another way and to tell you instead (it used to suggest you could "add an exception"); (2) commands are matched after undoing simple disguises (joined strings, escapes, split paths), and Python/Node scripts are checked for autostart paths anywhere; (3) after a refusal, the infection check reviews every later call in that chat and ends the task on a workaround, and the agent can no longer read or change the safety plugins' files; (4) a **startup tripwire** checks Windows' autostart locations (Run keys, Startup folders, scheduled tasks, services) around every tool call that can change the system, undoes anything new (kept in `usr/safety_quarantine/`), and stops the task. Agent Zero's own "Start with Windows" entry is left alone.
- `Format-Hex`, `Format-Table` and other `Format-*` commands were refused as "disk formatting"; only real disk formatting (`format D:`, `Format-Volume`, `Clear-Disk`) is now.
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
