# Skills Plugin DOX

## Purpose

- Own active and hidden skill configuration injected into prompt protocol on each turn.

## Ownership

- `hooks.py` owns skill prompt injection and plugin lifecycle behavior.
- `api/skills_catalog.py` owns skill catalog access.
- `prompts/agent.system.active_skills.md` owns injected active-skill prompt content.
- `tools/skill_learn.py`, `helpers/learned.py` and `prompts/agent.system.tool.skill_learn.md` own agent-learned skills: the offer-then-draft flow, deterministic draft checks, approval, install and versions.
- `webui/` owns skill settings UI and store.
- `default_config.yaml`, `plugin.yaml`, `README.md`, and `LICENSE` own defaults, metadata, docs, and license.

## Local Contracts

- Keep active skill lists bounded by configured caps.
- Store configured skills in normalized portable paths.
- Hidden skills affect catalog/search/load visibility but must not be injected as active prompt content.
- Agent-learned skills are only drafted after the user agrees in chat, are refused by `learned.check_draft` (injection phrasing, encoded or downloaded code, Defender/firewall switches, credentials, permission/audit files), and are installed only after `_permissions/helpers/ask.request_approval` - in every mode, Bypass included. `skill_learn` is self-confirming in `_permissions/helpers/rules.py` so the gate doesn't ask twice; plan mode refuses drafts.
- Drafts live in `usr/skills/.pending/<name>/` and old versions in `usr/skills/<name>/.versions/SKILL.v<N>.md`; both stay inert because skill discovery skips hidden folders. Frontmatter carries `origin: agent-learned`, `version`, `created`, `source_chat`. Never overwrite a learned skill without keeping the previous version.

## Work Guidance

- Coordinate active-skill resolution changes with core skill loading and settings UI.

## Verification

- Run skill runtime/catalog tests or smoke-test active, hidden, global, project, and chat-scope behavior after changes.
- `pytest tests/test_skill_learn.py` for agent-learned skills.

## Child DOX Index

No child DOX files.
