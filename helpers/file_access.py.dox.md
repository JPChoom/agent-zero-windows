# file_access.py DOX

## Purpose

- Own the File Browser's access policy on native Windows installs: which folders and drives a local or remote session may open, path validation, and A0's always-protected files.

## Ownership

- `file_access.py` owns the runtime implementation; this file owns its contracts.
- Public API: `SCOPES`, `REMOTE_SCOPES`, `SETTINGS_KEYS`, `AccessDenied`, `Policy`, `read_settings`, `policy_for`, `widens`, `resolve`, `resolve_new`, `validate_name`, `is_within`, `is_protected`, `contains_protected`, `list_drives`, `a0_base`, `workdir`, `system_drive_root`.
- Callers: `helpers/file_manager.py`, `api/file_manager*.py`, `api/security_settings.py` (`save_file_access`).

## Runtime Contracts

- Settings (written only by `api/security_settings.py save_file_access`; `helpers/settings.convert_in` ignores them via `SECURITY_OWNED_KEYS`): `file_browser_scope` `usr` / `a0_root` (default) / `full`; `file_browser_remote_scope` `usr` / `a0_root` (default) / `same`; `file_browser_allow_other_drives`, `file_browser_allow_removable_drives` (default off).
- Roots: `usr` = `<A0>/usr`; `a0_root` = the A0 folder; `full` = the Windows system drive plus A0's drive. The configured workdir is always a root. Drive toggles add other `fixed` / `removable` drives. Remote sessions get the narrower of local scope and remote cap, and drive toggles only when the cap is `same`.
- `resolve` accepts only absolute drive paths (`C:\...`, `/` treated as `\`), refuses UNC/device paths, alternate data streams, NUL bytes and reserved device names (`NUL`, `CON`, `COM1`...), resolves links/junctions with `os.path.realpath`, then requires the real path inside a root (`is_within`: case-insensitive, whole components) and not protected.
- Protected in every mode (`is_protected`): `<A0>/.env`, `usr/.env`, any `secrets.env` under `usr/` or a `.a0proj`, `usr/permissions_bypass.json`, `usr/security_audit*.jsonl`, `usr/plugins/_oauth/**`, `usr/whatsapp/bridge-runtime/**`, plugin `config.json` under `usr/plugins`, `usr/agents` or a `.a0proj`. `contains_protected` refuses folder-level changes that would include one (and refuses past 20,000 entries).
- `list_drives` (cached 5 s): ctypes `GetLogicalDrives` / `GetDriveTypeW`; kinds `system` (Windows or A0 drive), `fixed`, `removable` (removable type, or USB/SD/MMC bus via `IOCTL_STORAGE_QUERY_PROPERTY`, since Windows reports USB disks as fixed), `network`, `cdrom`. Drives without media are skipped. Network drives are never roots.
- `widens(new, old)` is true when either the local or the remote policy gains a root.

## Verification

- `pytest tests/test_file_access.py tests/test_file_manager.py`

## Child DOX Index

No child DOX files.
