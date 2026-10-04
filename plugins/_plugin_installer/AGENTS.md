# Plugin Installer DOX

## Purpose

- Own installing and updating plugins from ZIP uploads, Git repositories, and the community Plugin Index.

## Ownership

- `helpers/install.py` owns archive extraction, Git install/update, validation, hook execution, and install finalization.
- `api/plugin_install.py` owns install/update/index API dispatch.
- `webui/` owns Plugin Hub, ZIP, Git, detail, and shared install UI.
- `plugin.yaml` and `README.md` own metadata and behavior notes.

## Local Contracts

- Install third-party plugins into `usr/plugins/`, not bundled `plugins/`.
- Reject unsafe archive paths, missing manifests, invalid manifests, and plugin name conflicts.
- New ZIP/Git/Hub installs are marked review-pending (`mark_review_pending`) and do NOT run their install hook; the hook runs when the user first enables the plugin globally (`helpers/plugins.py toggle_plugin`). Results include `review_pending` and `message`.
- Git updates of an already-enabled plugin still run pre-update and install hooks (the user explicitly asked to update).
- Refresh plugin state after successful changes.

## Work Guidance

- Keep installer validation aligned with plugin contracts and Plugin Index expectations.

## Verification

- Smoke-test ZIP install, Git install, Plugin Hub install, and Git update paths after changes.

## Child DOX Index

No child DOX files.
