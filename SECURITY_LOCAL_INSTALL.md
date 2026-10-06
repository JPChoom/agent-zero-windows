# Local Installation Security

- Keep `WEB_UI_HOST=localhost`; do not expose Agent Zero directly to LAN or Internet.
- Install it on a dedicated secondary PC (the intended setup). There is no sandbox: on your main PC it runs at your own risk.
- Run Agent Zero as a standard, non-administrator Windows account.
- UI authentication is enabled in `usr/.env`. Delete `FIRST_RUN_CREDENTIALS.txt` after first use.
- Terminal Access is disabled by default. Its safeguards are defense-in-depth, not a sandbox.
- Use `scripts/export_safe_source.ps1` when sharing or backing up source code.
- Rotate credentials after accidentally sharing `usr/.env`, logs, chats, or memory files.
- Use `scripts/verify_install.ps1` after upgrades.
