# Fixes applied

- Corrected the `tools/search_engine.py` indentation/import failure and retained SearXNG-to-DuckDuckGo fallback behavior.
- Removed the duplicate `helpers.extension` import in `agent.py`.
- Removed the duplicate `crontab==1.0.1` requirement.
- Enabled UI authentication and rotated local handshake credentials.
- Disabled Terminal Access by default and added authentication, CSRF, workspace confinement, command screening, secret filtering, timeout, output limits, and corrected plugin API/tool interfaces.
- Added controlled-shutdown chat persistence and explicit log flushing.
- Added safe-export, cache-cleanup, and validation PowerShell scripts.
- Added runtime/secret exclusions to `.gitignore` and local-install security guidance.

## Deliberately not automated

Exact dependency locking and full test execution require the omitted Windows `.venv`. Run `scripts\verify_install.ps1` after placing this tree over the existing installation. Architectural relocation of runtime data was not forced because changing paths without the complete runtime environment could break existing chats, projects, and extensions.
