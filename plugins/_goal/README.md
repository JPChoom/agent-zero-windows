# Goal

Built-in per-chat goal tracking, ported from upstream `agent0ai/agent-zero`'s
`_goal` plugin (current `main` branch, fetched via `gh api`). This one
ported essentially verbatim - it's pure Python/JS business logic with no
Docker or A0-CLI-bridge dependencies, unlike `_orchestrator`/`_commands`.

## What it does

- Lets the user (or the model) set a single objective for a chat: `goal.py`
  stores it as JSON under `usr/plugins/_goal/goals/<context_id>.json`.
- A goal strip renders above the chat input (`chat-input-progress-start`
  extension point) showing status, objective, and elapsed active time, with
  inline edit/pause/resume/delete controls.
- While a goal is `active`, the `response` tool is overridden
  (`tools/response.py`) so a normal response doesn't end the turn - the
  agent is told to keep working toward the goal instead, until it marks the
  goal `complete` or `blocked` itself via the `goal` tool.
- The current goal is injected into the prompt each loop iteration via
  `extensions/python/message_loop_prompts_after/_50_include_goal.py`.
- Depends on the `_commands` plugin for its `/goal` slash command
  (`commands/goal.command.yaml` + `goal_command.py`) - install both, or the
  `/goal` shortcut won't resolve (the `goal` tool and the strip UI work
  regardless, since neither depends on `_commands`).

## Commands

`/goal` with no argument shows status. Supported sub-actions: `pause`,
`resume`, `edit <text>`, `delete`, `complete`, `blocked [note]`, `auto
[hint]` (asks the model to set its own goal), or any other text to set a
new goal directly.

## Fork adaptations

- `<x-icon>` → `<span class="material-symbols-outlined">` in
  `goal-strip.html`, matching this fork's actual icon convention (see
  `plugins/_commands/README.md` for the same note - this fork's frontend
  doesn't have upstream's `<x-icon>` custom element).

Everything else - `tools/goal.py`, `tools/response.py`, `api/goal.py`,
`goal_command.py`, the message-loop extension, `goal-store.js` - is a
verbatim port; every dependency (`helpers.files`, `helpers.tool`,
`helpers.extension`, `tools.response.ResponseTool`,
`Agent.hist_add_tool_result`) was checked against this fork's actual code
before porting.
