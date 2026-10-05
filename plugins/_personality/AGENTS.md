# _personality Plugin DOX

## Purpose

- Named system-prompt overlays (e.g. Brutally Honest) chosen per chat on top of the active agent profile.

## Ownership

- `helpers/config.py` owns the personality list (read/write through `helpers.plugins` plugin config).
- `api/` owns list/save/set/delete; `extensions/python/system_prompt/` appends the active overlay; `webui/` owns the selector.

## Local Contracts

- The user's personality list is plugin config saved under `usr/plugins/_personality/config.json`, never in this folder; `default_config.yaml` ships only the built-ins.
- The active personality is stored per chat in `context.data["personality"]`.
- The `default` personality has an empty prompt and cannot be deleted.

## Work Guidance

## Verification

- Smoke-test selecting, creating, editing, and deleting a personality and that the overlay reaches the system prompt.

## Child DOX Index

No child DOX files.
