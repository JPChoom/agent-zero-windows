---
name: orchestrator
description: Use when delegating coding or repository work to an external terminal coding agent (Claude Code, Codex, Cursor CLI, Gemini CLI, Grok Build, Hermes Agent, or OpenCode).
triggers:
  - "terminal agent"
  - "external coding agent"
  - "delegate to codex"
  - "delegate to claude code"
  - "delegate to cursor"
  - "delegate to cursor cli"
  - "delegate to gemini cli"
  - "delegate to grok build"
  - "delegate to hermes"
  - "delegate to opencode"
allowed_tools:
  - code_execution_tool
  - memory_load
  - memory_save
---

# Orchestrator

Use `code_execution_tool` (PowerShell) to run external terminal coding
agents. There is no `terminal_agent` tool: this skill exists so these heavy
delegation instructions load only when the task actually needs them.

This Agent Zero instance runs natively on the host machine - `code_execution_tool`
already has direct host access. There is no separate "host vs. container"
question to ask; just run the commands below.

## Rules

- Always choose an explicit working directory (`$WORKDIR`) for repository
  work. Prefer the user's actual project path over Agent Zero's default
  workdir. Every command below assumes you `cd` there first.
- Setup is part of the workflow: check whether the CLI is installed, install
  only the requested CLI if missing, probe its version/help, run a tiny
  smoke prompt, then run the real task.
- Keep authentication human-in-the-loop. You may start the CLI's
  login/setup command, relay the exact URL, device code, or prompt to the
  user, then wait for the user to confirm completion before retrying the
  smoke prompt.
- Never start a full-screen CLI/TUI as a login fallback. If a command
  accidentally opens one and shows welcome/theme/provider/unreadable menu
  output, reset the terminal session instead of sending keys into it.
- If login/setup shows a menu or provider choices, show those choices to the
  user in chat and ask which one to select. Keep the terminal session open,
  then send the user's selected number/key back to that session.
- Never ask the user to paste secrets into chat unless there is no safer
  path. Prefer the CLI's own browser/device login, or an environment
  variable/secret set outside chat (Agent Zero's secrets system, or
  `usr/.env` under the install root - see each reference for the exact
  variable name).
- For long-running commands, start the CLI in a shell session and poll that
  session's output. Do not add your own timeout wrapper around it.
- Pass a self-contained task brief: goal, target files or repo path,
  constraints, verification commands, and expected output.
- After the delegated agent finishes, inspect its output and verify
  important changes yourself before reporting success - it ran with its own
  approval gate bypassed (see README.md), so nothing else checked its work
  as it went.
- You can consult more than one delegated agent in one workflow. Keep their
  shell sessions separate, label which agent produced each answer, and
  compare results before acting.

## Workflow

1. Read the relevant agent's reference file under `references/` (listed
   below) - only that one file, not all of them.
2. Check install with the reference's install command.
3. If missing, install only that requested CLI with the command listed in
   its reference, then run the install check again.
4. Probe `--version` or `--help`.
5. Run the reference's smoke prompt.
6. If the smoke prompt reports missing auth, run only the login/setup
   command named in that reference; do not run the bare CLI as a login
   fallback. Relay URLs, device codes, prompts, and visible menu choices to
   the user in chat, then wait. If a prior command left a TUI open, reset
   the terminal session before continuing.
7. After the user confirms, rerun the smoke prompt. Only then run the real
   task, replacing the smoke prompt's text with the actual task brief.

If the user has a standing preference for which agent to use for a given
kind of task, save it with `memory_save` after they choose once, and check
`memory_load` before asking again next time.

## Reference Files

- Codex CLI: `references/codex.md`
- Claude Code: `references/claude.md`
- Cursor CLI: `references/cursor.md`
- Gemini CLI: `references/gemini.md`
- Grok Build: `references/grok.md`
- Hermes Agent: `references/hermes.md`
- OpenCode: `references/opencode.md`

Keep generic orchestration rules here. Put agent-specific commands, auth
quirks, install hints, and smoke prompts in the matching reference file.
