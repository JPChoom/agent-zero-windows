# Orchestrator Skills - AGENTS.md

## Purpose

- Own the plugin's load-on-demand skill collection.
- Keep external-agent orchestration instructions available only when the
  user asks for terminal coding-agent delegation.

## Ownership

- Owns skill folders under `skills/`, currently `orchestrator/`.
- Does not own Python adapter code or settings UI - this fork's port does
  not include either (see `../README.md` for what was left out and why).

## Local Contracts

- Skills must use Agent Zero's ordinary `code_execution_tool` (PowerShell on
  this native-Windows fork), not a plugin-specific terminal agent tool.
- Skill instructions plus their local reference files must be self-contained
  enough for the agent to run install checks, login/setup, smoke prompts,
  real tasks, and verification.
- Generic orchestration belongs in `SKILL.md`; per-agent details belong in
  the nearest `references/` file.
- The skill must instruct agents not to paste or request secrets in chat
  when a safer browser/device/login-prompt path exists.
- The skill must instruct agents not to use Computer Use to operate
  coding-agent terminals or TUIs.

## Work Guidance

- Keep the SKILL.md text operational, not encyclopedic.
- Add or update per-agent reference files when CLI-specific commands or auth
  behavior change.

## Verification

- Manually inspect SKILL.md frontmatter (YAML) and each reference file's
  command blocks after edits - there is no automated skill-content test in
  this fork's port.

## Child DOX Index

| Child | Scope |
| --- | --- |
| [orchestrator/AGENTS.md](orchestrator/AGENTS.md) | The `orchestrator` skill manifest and delegation workflow body. |
