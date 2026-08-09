# Orchestrator Plugin DOX

## Purpose

- Own the load-on-demand `orchestrator` skill that tells Agent Zero how to
  delegate coding/repository work to external terminal coding agent CLIs.
- Keep the heavy per-agent delegation instructions out of the always-loaded
  system prompt - they only load when a task actually needs them.

## Ownership

- `plugin.yaml` owns the always-discoverable plugin metadata.
- `skills/orchestrator/SKILL.md` owns the generic orchestration loop: when to
  delegate, how to pick an execution place, setup/smoke-test discipline,
  auth handling.
- `skills/orchestrator/references/*.md` each own one external agent's exact
  non-interactive command syntax, install/probe steps, and auth quirks.

## Local Contracts

- This is a **skill-only** port of upstream `agent0ai/agent-zero`'s
  `_orchestrator` plugin (see README.md for what was intentionally left out
  and why).
- Ported this port on `2026-08-09`, adapted for a fork that runs Agent Zero
  natively on Windows rather than in Docker: `code_execution_tool` already
  runs on the host machine here, so the upstream host/A0-CLI-bridge vs.
  container split does not apply - references use `code_execution_tool`
  directly and PowerShell command syntax.
- Delegated agents run with their own approval/sandbox gates bypassed (e.g.
  `--permission-mode bypassPermissions`, `--dangerously-bypass-approvals-and-sandbox`),
  matching upstream's default. This means `_safety_policy`'s command gate,
  kill switch, and audit log do **not** see what a delegated agent does
  internally - only the one `code_execution_tool` call that launched it. This
  was a deliberate, explicit choice (see chat history / README.md), not an
  oversight.

## Work Guidance

- Keep per-agent command syntax in its own reference file; keep the generic
  loop in SKILL.md.
- If a referenced CLI's non-interactive flags change upstream, update only
  that reference file.

## Verification

- `helpers/skills.py`'s skill scan should discover `skills/orchestrator/SKILL.md`
  automatically (`plugins/*/skills` glob) - no registration code needed.
- Manually inspect SKILL.md frontmatter (YAML) after edits.

## Child DOX Index

No child DOX files.
