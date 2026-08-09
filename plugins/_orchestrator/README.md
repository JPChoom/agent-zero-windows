# Orchestrator

A load-on-demand `orchestrator` skill that tells Agent Zero how to delegate
coding/repository work to external terminal coding agent CLIs: Claude Code,
OpenAI Codex, Cursor CLI, Gemini CLI, Grok Build, Hermes Agent, or OpenCode.

This is a partial port of upstream `agent0ai/agent-zero`'s `_orchestrator`
plugin, adapted for this fork and scoped down deliberately - see "What was
left out" below before assuming feature parity with upstream.

## How it works

There is no `terminal_agent` tool. The skill exists so these delegation
instructions - install/probe steps, non-interactive command syntax, auth
handling for each CLI - only load into context when a task actually needs
them, not on every turn.

Ask Agent Zero to delegate to one of the supported agents (or just describe
a task that clearly calls for it - the skill's `triggers` list catches
phrases like "delegate to codex" or "use claude code for this"). It reads
`skills/orchestrator/SKILL.md` for the general loop, then the one reference
file under `skills/orchestrator/references/` for the agent actually being
used.

## Why this differs from upstream

Upstream's plugin is built around two execution places: the user's own host
machine (reached through a separate "A0 CLI" bridge product, since upstream
Agent Zero runs in a Docker container) and the Agent Zero container itself.

This fork runs Agent Zero **natively on Windows**, not in Docker - there is
no container to bridge out of. `code_execution_tool` already executes
directly on the host machine. So the host-vs-container split, the A0 CLI
bridge install instructions, and the "should I use your local CLI or the one
in my container?" question that upstream's skill asks are all not
applicable here and have been removed. References use `code_execution_tool`
directly with PowerShell command syntax instead of the bash upstream ships.

## What was left out (this pass)

Only the skill and its reference docs were ported. Not ported, and not
present in this fork's `_orchestrator`:

- **`helpers/adapters/*.py` + Settings > External Services status UI.**
  Upstream's dashboard shows which CLIs are installed and their detected
  auth state. Useful, but not load-bearing - the skill works without it by
  checking `Get-Command <cli>` itself as part of its install/probe step. Can
  be added later if the manual check becomes annoying.
- **Codex plugin-owned device-code login** (`api/start_device_login.py`,
  `api/poll_device_login.py`, credential storage under the plugin's own data
  dir). References here rely on the CLI's own `codex login`/`claude auth
  login`/etc. instead.
- **Delegating to another Agent Zero instance** (upstream's `a0` adapter/
  reference). Upstream reaches other Agent Zero instances through the same
  A0 CLI bridge product this port already excludes, and there's no bundled
  `a0 headless`-style CLI in this repo to reach one directly. Left out
  entirely rather than shipping a reference file that can't actually work -
  can be revisited if a concrete way to reach another instance is needed.

## A safety-policy gap, on purpose - read this before enabling delegation

Every reference here matches upstream's default of **bypassing the
delegated agent's own approval/sandbox gate** for non-interactive use:
`claude ... --permission-mode bypassPermissions --allowedTools Bash,Read,Edit`,
`codex exec --dangerously-bypass-approvals-and-sandbox`, Gemini's
`--approval-mode=yolo`, Grok's `--always-approve`, and so on.

Once one of these starts, it is running its **own** autonomous tool loop -
reading, writing, and executing inside `$WORKDIR` - and none of that is
visible to this fork's `_safety_policy` plugin (command-gate, kill switch,
approval tiers) or its audit log. Those only ever see the single
`code_execution_tool` call that launched the delegated CLI, not what it does
internally. This was a deliberate choice (matching upstream's own default,
made explicitly when this port was scoped) favoring capability over
in-the-loop oversight for delegated work - not an oversight. If you want a
human checkpoint before a delegated agent starts running unsupervised, that
would mean wiring delegation through `_safety_policy`'s existing
approval-tier flow instead, which this pass does not do.

## Reference Files

- Codex CLI: `references/codex.md`
- Claude Code: `references/claude.md`
- Cursor CLI: `references/cursor.md`
- Gemini CLI: `references/gemini.md`
- Grok Build: `references/grok.md`
- Hermes Agent: `references/hermes.md`
- OpenCode: `references/opencode.md`
