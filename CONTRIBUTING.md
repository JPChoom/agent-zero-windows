# Contributing to Agent Zero for Windows

Thanks for helping. This is an unofficial, Windows-native fork of [Agent Zero](https://github.com/agent0ai/agent-zero); contributions here should target the Windows fork.

## Where a change belongs

- **Windows-native behavior, security hardening, the WebUI theme, or fork-specific plugins:** open an issue or pull request in this repository.
- **A bug that also exists in upstream Agent Zero (Docker/Linux or platform-independent core):** please report it upstream at [agent0ai/agent-zero](https://github.com/agent0ai/agent-zero). If you fix it here, mention that it is an upstream issue so it can be forwarded.
- **A community plugin:** publish it in its own repository and submit it to upstream's Plugin Index ([agent0ai/a0-plugins](https://github.com/agent0ai/a0-plugins)).

## Quick rules

- Keep each pull request to one focused change.
- Run the tests on Windows and include the result: `.\.venv\Scripts\python.exe -m pytest -q tests`. If something is blocked, say why. Tests that only make sense on Linux/Docker use the markers in `tests/conftest.py` (`posix_only`, `linux_only`, `docker_layout`, `needs_symlinks`) so they skip cleanly instead of failing.
- Follow the per-folder contracts in [AGENTS.md](AGENTS.md) (the "DOX" files): read the `AGENTS.md` for every folder you touch, and update it - and any matching `*.py.dox.md` - when behavior or structure changes.
- Match the surrounding code: naming, comment density, and idioms.
- Frontend changes: check desktop and phone widths, and the Solid, Glass and Enhanced materials.

## Privacy and security (required)

- **Never include private data** in an issue, log excerpt or patch: chats, memory, `usr/` contents, `.env` files, API keys or tokens, passwords, personal email addresses, real IP addresses, or local user paths such as `C:\Users\<you>`. Use placeholders like `203.0.113.x` and `example.com`.
- The `usr/` folder is git-ignored on purpose; do not force-add anything from it.
- Do not weaken the security model (tunnel allowlist, locked Bypass mode, CSRF and authentication checks, untrusted-content wrapping) without discussing it first in an issue.
- Report vulnerabilities privately through GitHub's *Security > Report a vulnerability*, not in a public issue.

## Commits

Use a clear, imperative subject line (for example "Fix Time Travel lock race") with a short body explaining why. Configure git with your GitHub noreply address if you do not want your email public:

```powershell
git config user.email "<id>+<username>@users.noreply.github.com"
```

## License

By contributing you agree that your contribution is licensed under the repository's [MIT License](LICENSE).
