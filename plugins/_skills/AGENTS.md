# Skills Plugin DOX

## Purpose

- Own active and hidden skill configuration injected into prompt protocol on each turn.

## Ownership

- `hooks.py` owns skill prompt injection and plugin lifecycle behavior.
- `api/skills_catalog.py` owns skill catalog access.
- `prompts/agent.system.active_skills.md` owns injected active-skill prompt content.
- `tools/skill_learn.py`, `helpers/learned.py` and `prompts/agent.system.tool.skill_learn.md` own agent-learned skills: "learn that skill", deterministic draft checks, approval, install, versions, review, disable/delete and usage stats.
- `helpers/task_watch.py` and the hooks `monologue_start/_20_skill_task_start.py`, `tool_execute_after/_20_skill_task_step.py`, `monologue_end/_60_learn_skill.py` own task tracking (per chat context, so subordinate steps count) and starting self-learning; `helpers/auto_learn.py` and `prompts/skill_learn.auto.sys.md` own the background decision and placement.
- `api/learned_skills.py`, `webui/learned-skills.html`, `webui/learned-skills-store.js` and `extensions/webui/sidebar-quick-actions-dropdown-start/learned-skills-entry.html` own the Learned skills window.
- `webui/` owns skill settings UI and store.
- `default_config.yaml`, `plugin.yaml`, `README.md`, and `LICENSE` own defaults, metadata, docs, and license.

## Local Contracts

- Keep active skill lists bounded by configured caps.
- Store configured skills in normalized portable paths.
- Hidden skills affect catalog/search/load visibility but must not be injected as active prompt content.
- Every learned skill passes `learned.check_draft` (injection phrasing, encoded or downloaded code, Defender/firewall switches, credentials, permission/audit files) or is refused.
- Where it goes depends on what its task read (`learned.outside_source`: web search, browser, URL documents, A2A, MCP tools, network commands in terminal code): none -> installed directly (owner decision 2026-11-01); any -> self-learned skills wait in `usr/skills/.pending/<name>/` with `REVIEW.json` ("Needs a look"), and `skill_learn` asks via `_permissions/helpers/ask.request_approval` in every mode, Bypass included. `skill_learn` is self-confirming in `_permissions/helpers/rules.py` so the gate doesn't ask twice; plan mode refuses drafts.
- Self-learning (`auto_learn`, `auto_learn_min_steps`, `auto_learn_min_seconds`) runs only after an answered top-agent task that used no learned skill, in the background via `model_concurrency.run_when_idle` (caller `skill_learn_auto`, preemptible); it never overwrites a user's own skill of the same name, and updates a learned one only as its next version.
- Drafts live in `usr/skills/.pending/<name>/`, old versions in `usr/skills/<name>/.versions/SKILL.v<N>.md`, turned-off skills in `usr/skills/.disabled/<name>/`, deleted ones in `usr/skills/.deleted/<name>-<time>/`; all stay inert because skill discovery skips hidden folders. Frontmatter carries `origin: agent-learned`, `learned_by` (auto | asked), `version`, `created`, `source_chat`; stats in `usr/skills/.learned-stats.json`. Never overwrite a learned skill without keeping the previous version.

## Work Guidance

- Coordinate active-skill resolution changes with core skill loading and settings UI.

## Verification

- Run skill runtime/catalog tests or smoke-test active, hidden, global, project, and chat-scope behavior after changes.
- `pytest tests/test_skill_learn.py tests/test_skill_auto_learn.py` for agent-learned and self-learned skills.

## Child DOX Index

No child DOX files.
