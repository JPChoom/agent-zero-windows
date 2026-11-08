# WhatsApp Integration Plugin DOX

## Purpose

- Own WhatsApp communication through a Baileys-based Node.js bridge.

## Ownership

- `helpers/bridge_manager.py` owns bridge lifecycle. The bridge process, its config and lock (`_bridge`), and the poll task (`handler.POLL["task"]`) live in `helpers.chat_channels.registry("whatsapp")`, never in plugin module globals: plugin modules are re-imported when bundled plugin files change, and lost state starts a second bridge and poll loop.
- `helpers/handler.py` and `helpers/wa_client.py` own message routing and bridge API interaction.
- `helpers/storage_paths.py`, attachment helpers, and number utilities own storage, attachment, and phone-number handling.
- `whatsapp-bridge/` owns the Node.js bridge package.
- `api/`, `prompts/`, `extensions/`, `default_config.yaml`, `plugin.yaml`, `README.md`, and `webui/` own QR/start/disconnect/test endpoints, prompt fragments, hooks, settings, metadata, docs, and UI.

## Local Contracts

- An empty `allowed_numbers` answers nobody (one rule for every channel, owner decision 2026-11-08); `helpers/allowlist.py` tells phone approvals whether the list is set.

- Treat WhatsApp sessions, QR data, phone numbers, attachments, and bridge state as sensitive.
- Keep allowed-number and group-response controls enforced.
- Do not leave unmanaged bridge services outside plugin-owned runtime paths.

## Work Guidance

- Coordinate Node bridge changes with Python bridge client and settings UI.

## Verification

- Smoke-test dependency install, bridge start, QR pairing, allowed-number filtering, message routing, and replies when practical.

## Child DOX Index

No child DOX files.
