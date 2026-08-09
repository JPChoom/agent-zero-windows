# Orchestrator Skill - AGENTS.md

## Purpose

- Own the `orchestrator` skill: SKILL.md frontmatter/manifest and the
  generic delegation workflow body.

## Ownership

- `SKILL.md` owns the skill manifest (name/description/triggers/allowed_tools)
  and the generic delegation loop.
- `references/` owns exact per-agent command syntax - see its own AGENTS.md.

## Local Contracts

- `SKILL.md`'s frontmatter must stay valid YAML (`name`, `description`,
  `triggers`, `allowed_tools`) - `helpers/skills.py` parses it at scan time.
- Keep `SKILL.md` scoped to the loop that's the same across every delegated
  agent; per-agent specifics belong in `references/`.

## Work Guidance

- If `code_execution_tool`'s behavior changes in a way that affects
  non-interactive shell delegation, update this skill's workflow section.

## Verification

- Manually inspect frontmatter validity after edits.

## Child DOX Index

| Child | Scope |
| --- | --- |
| [references/AGENTS.md](references/AGENTS.md) | Per-agent command reference files. |
