# Terminal Access Plugin (Hardened)

This plugin is **disabled by default**. Enable it only for a trusted local installation by setting `TERMINAL_ACCESS_ENABLED=true` in `usr/.env`.

Security controls include required UI authentication and CSRF, a fixed working directory (`TERMINAL_ACCESS_ROOT`), timeout and output limits, environment-secret filtering, shell validation, and rejection of common downloader, persistence, credential, destructive-system, encoded-command, and reboot commands.

These controls reduce risk but do not make arbitrary command execution safe for network exposure. Keep `WEB_UI_HOST=localhost`, use a non-administrator Windows account, and do not expose the endpoint through a tunnel or reverse proxy.
