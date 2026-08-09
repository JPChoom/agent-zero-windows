# Goal Plugin DOX

## Purpose

- Own the built-in chat goal strip, `/goal` slash command, goal state API, and agent-facing goal tools.
- Keep chat goals scoped to the active chat context and stored as user data outside tracked plugin code.

## Ownership

- `plugin.yaml` owns the always-enabled `_goal` plugin metadata.
- `tools/goal.py` owns the single agent-facing goal tool, file-backed state under `usr/plugins/_goal/goals/`, and goal status normalization.
- `tools/response.py` owns the `response` tool override that keeps a chat going while a goal is active.
- `api/goal.py` owns the WebUI JSON API for reading, editing, pausing, resuming, and deleting goals.
- `commands/` owns the `/goal` slash command contributed to `_commands` (this plugin does not function as a slash command without `_commands` installed - see README.md).
- `extensions/webui/chat-input-progress-start/goal-strip.html` and `webui/goal-store.js` own the composer goal strip and inline controls.
- `extensions/python/message_loop_prompts_after/_50_include_goal.py` owns injecting the active goal into the prompt each loop iteration.
- `prompts/` own agent-facing goal instructions.

## Local Contracts

- This is a port of upstream `agent0ai/agent-zero`'s `_goal` plugin - see
  `README.md` for the one adaptation made (icon markup). Otherwise
  verbatim; every dependency was checked against this fork's actual code
  before porting, not assumed.
- Goal state lives in `usr/plugins/_goal/goals/<context_id>.json`, one file
  per chat context - not a database table, not part of the tracked plugin
  source.

## Work Guidance

- Keep `tools/goal.py` as the single source of truth for goal state
  read/write; the API handler and command script should call into it, not
  duplicate its logic (matches upstream's own structure).
- `tools/response.py`'s override only fires when a goal is `active` -
  don't broaden that check without checking `FINAL_STATUSES`/
  `ACTIVE_STATUSES` in `tools/goal.py` first.

## Verification

- Manually inspect JSON goal files for valid structure if debugging state.
- Live-verify: set a goal via `/goal <objective>` or the `goal` tool, confirm the strip renders above the chat input, confirm the `response` tool doesn't end the turn while the goal is active.

## Child DOX Index

No child DOX files.
