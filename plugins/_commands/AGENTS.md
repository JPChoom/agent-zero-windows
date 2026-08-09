# Commands Plugin DOX

## Purpose

- Own the built-in slash command manager and chat composer slash picker.
- Keep file-backed `/command` discovery consistent across project, global, and plugin-provided scopes.

## Ownership

- `plugin.yaml` owns the built-in `_commands` plugin metadata.
- `helpers/commands.py` owns command name sanitization, argument parsing, scope resolution, file persistence, plugin command discovery, and command invocation resolution.
- `api/commands.py` owns the Commands API actions used by the WebUI.
- `webui/` owns the manager/editor modal stores and HTML surfaces.
- `commands/` owns bundled read-only slash command definitions shipped by `_commands`.
- `extensions/` owns the chat composer slash picker and incoming-message command resolution.
- `skills/commands-create-slash-command/` owns the agent-facing skill for authoring new commands.

## Local Contracts

- This is a port of upstream `agent0ai/agent-zero`'s `_commands` plugin -
  see `README.md`'s "What changed from upstream" section before assuming
  parity with upstream docs/behavior. Notably: `/stop` uses
  `AgentContext.kill_process()` (no local `api/stop.py`), icons use
  `<span class="material-symbols-outlined">` not upstream's `<x-icon>`,
  and there is no legacy-plugin migration extension.
- `helpers/commands.py` is otherwise a near-verbatim port - every core
  dependency it calls (`helpers.plugins`, `helpers.projects`,
  `helpers.yaml`, `helpers.skills.split_frontmatter`) was verified to
  exist locally with matching signatures before porting, not assumed.
- Commands are file-backed (`.command.yaml` + `.txt`/`.py`), not database
  rows - see `helpers/commands.py`'s scope-directory functions for the
  precedence order.

## Work Guidance

- Keep `helpers/commands.py` as the single source of truth for command
  parsing/resolution; API and script hooks should call into it, not
  duplicate its logic.
- When adding a new built-in command, add both the `.command.yaml` and its
  content file to `commands/`, and route script-type commands through
  `commands/connector_commands.py`'s dispatch unless it's a genuinely
  separate concern (like `_goal`'s own `goal_command.py`).

## Verification

- Manually inspect `.command.yaml` files for valid YAML after edits.
- Run `pytest tests/test_commands_plugin.py` (this fork's own test file,
  not upstream's - see that file's docstring) after changing
  `helpers/commands.py` or `api/commands.py`.
- Live-verify the chat composer picker (type `/`) and at least one
  built-in command (`/status`, `/new`) after touching the extension hooks
  or webui stores.

## Child DOX Index

No child DOX files.
