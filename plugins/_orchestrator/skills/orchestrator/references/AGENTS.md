# Terminal Agent References - AGENTS.md

## Purpose

- Own per-agent command references for the `orchestrator` skill.
- Keep `SKILL.md` generic while preserving exact install, auth, smoke, and
  run commands for each supported terminal coding agent.

## Ownership

- Owns one markdown file per agent id: `codex.md`, `claude.md`, `cursor.md`,
  `gemini.md`, `grok.md`, `hermes.md`, `opencode.md`. (Upstream also has an
  `a0.md` for delegating to another Agent Zero instance via a separate
  bridge product this fork's port doesn't include - see `../../README.md`.)
- Does not own global orchestration rules (those live in `../SKILL.md`).

## Local Contracts

- Each reference must include: when to use the agent, install/probe
  commands, auth/setup behavior, smoke command, and real-task command shape.
- Generic rules (no bare CLI fallback, no secrets in chat, explicit workdir,
  smoke-before-real) stay in `../SKILL.md`, not duplicated per file.
- Reference filenames must match the agent's CLI binary name where possible.
- Commands are PowerShell, matching this fork's native-Windows execution
  environment - not the bash upstream ships.
- When adding a reference, update `../SKILL.md`'s reference index too.

## Work Guidance

- Keep each file operational and short enough that the agent can copy a
  command block safely without re-deriving syntax.
- Redact or avoid secrets; use environment variables or Agent Zero's
  `§§secret(...)` placeholder without printing expanded values.

## Verification

- Manually inspect command blocks after edits; there is no automated test
  for reference content in this fork's port.

## Child DOX Index

No child DOX files.
