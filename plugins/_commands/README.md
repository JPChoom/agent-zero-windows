# Commands

YAML-configured slash commands for Agent Zero, ported from upstream
`agent0ai/agent-zero`'s `_commands` plugin (current `main` branch, fetched
via `gh api`) and adapted for this fork.

This plugin lets you define reusable `/commands` as `.command.yaml` files with either:

- a `.txt` template body
- a `.py` script hook

Commands are managed from the plugin modal and can be inserted directly from the chat composer with prefix syntax (`/goal objective`) or an exact trailing command (`objective /goal`). The picker opens only for prefix syntax; trailing commands resolve when sent.

## What changed from upstream

- **`<x-icon>` → `<span class="material-symbols-outlined">`.** Upstream's
  WebUI has an `<x-icon name="...">` custom element this fork's frontend
  doesn't have; this fork uses Material Symbols spans directly everywhere
  else, so every icon reference in the ported HTML (`commands-menu.html`,
  `main.html`, `editor.html`) was translated to match.
- **`/stop` uses `AgentContext.kill_process()`, not `api.stop.stop_context`.**
  This fork doesn't have upstream's `api/stop.py`. `kill_process()`
  (`agent.py`) is the local equivalent: it kills the running task without
  resetting agent state or history, unlike `.reset()`.
- **No legacy-plugin migration.** Upstream ships a startup-migration
  extension that copies data from an older community `commands` plugin
  namespace into `_commands`. Not ported - there's no legacy `commands`
  plugin installed here to migrate from, and it would be dead code.
- **`/browser host` and `/computer-use` degrade gracefully, same as
  upstream.** Both reference the separate "A0 CLI"/Launcher host-bridge
  product this fork doesn't include (see `plugins/_orchestrator/README.md`
  for the same gap on that plugin). The code already checks for a
  connected bridge and reports "not connected" rather than erroring, so
  these commands work correctly - they just always report no bridge
  connected on this fork, which is accurate.

Everything else - the parser, the effect system, the manager UI, all
built-in session/queue/model/project commands not listed above - is a
faithful, mechanically-verified port: every Python/JS dependency it calls
into (`helpers.plugins`, `helpers.projects`, `helpers.message_queue`,
`helpers.integration_commands`, `helpers.state_monitor_integration`,
`plugins._a0_connector.helpers.ws_runtime`, the WebUI's chat/attachments/
notification/plugin-settings stores) was checked against this fork's
actual code before porting, not assumed.

## Features

- `.command.yaml` config files with command metadata
- Text template commands with `{}` placeholders and parsed args
- Python hook commands with parsed args and optional chat history payload
- Unified parser for positional args, free-form tail, and flags
- Prefix and postfix command resolution for WebUI and remote/AI-sent messages
- Scope-aware command resolution across project and global scopes
- Built-in command pack for common session, queue, model, project, and browser commands
- `/stop` control that uses the same hard-stop operation as the WebUI composer button
- Slash picker in the chat composer with keyboard navigation and create-on-empty flow

## Command File Model

Each command is defined by one config file plus one content file in the same scope directory.
Set `webui_hidden: true` to keep a command resolvable while omitting it from the chat composer picker.

Example text command:

`scan.command.yaml`

```yaml
name: scan
description: Scan a Git repository.
argument_hint: /scan --git-url https://github.com/org/repo
type: text
template_path: scan.txt
```

`scan.txt`

```txt
Please scan repository: {args.flags.git_url}

Raw input:
{raw}
```

Example python hook command:

`optimize.command.yaml`

```yaml
name: optimize
description: Optimize the current request.
argument_hint: /optimize 30%
type: script
script_path: optimize.py
include_history: true
```

`optimize.py`

```python
def run(payload):
    args = payload["arguments"]
    pct = args["positional"][0] if args["positional"] else "10%"
    return {
        "text": f"Optimize this response by {pct}.",
        "effects": [],
    }
```

## Argument Parsing

The parser supports:

- Positional input: `/scan https://github.com/org/repo`
- Postfix input: `https://github.com/org/repo /scan`
- Long flags: `/scan --git-url https://github.com/org/repo`
- Long flags with equals: `/scan --git-url=https://github.com/org/repo`
- Short flags and bundles: `/scan -v -q` or `/scan -vq`

Parsed data is available to:

- Text templates via `{}` placeholders:
  - `{raw}`
  - `{args.positional.0}`
  - `{args.flags.git_url}`
- Python scripts via `payload["arguments"]`

## Script Hook Contract

Python hook file must expose:

```python
def run(payload): ...
```

It can return:

- `str` (used as replacement text)
- `dict` with:
  - `text: str` (replacement text)
  - `effects: list[dict]`

Supported frontend effects:

- `{"type": "replace_input", "text": "..."}`
- `{"type": "append_input", "text": "..."}`
- `{"type": "toast", "level": "info|error|success", "message": "..."}`
- Built-in UI effects for existing WebUI actions such as chat switching, modals, attachments, compaction, queue actions, transcript copy, and toast output

## Scope Resolution

Commands are discovered from these scope folders (relative to the install
root, e.g. `C:\a0`):

- Project: `usr/projects/<project>/.a0proj/plugins/_commands/commands/`
- Global fallback: `usr/plugins/_commands/commands/`
- Built-in defaults: `plugins/_commands/commands/`
- Other enabled plugins: `plugins/<plugin>/commands/` or `usr/plugins/<plugin>/commands/`

Precedence in the chat picker:

1. Project
2. Global
3. Built-in `_commands`
4. Other plugin-distributed commands

## UI Surfaces

- Plugin modal: manage project/global commands and create editable same-name overrides of bundled commands
- Chat composer: type `/` at the start or as the final token to browse commands

## Agent Skill

The plugin ships with `commands-create-slash-command`, a plugin-scoped skill that helps Agent Zero create or update command files.
