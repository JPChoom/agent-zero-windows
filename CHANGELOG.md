# Changelog

All notable changes to Agent Zero for Windows. Versions are git tags (`vX.Y`).

## Unreleased

### Security
- Untrusted-content blocks carry a fresh random id per tool result (`<untrusted_content id="…">…</untrusted_content id="…">`), so a web page or file written in advance cannot contain the real closing tag. Tag-like text inside the content is neutralized in any case, spacing, HTML-entity or full-width form. Chats saved before this change still strip correctly for memory.
- Docs: a dedicated secondary PC is the intended setup; on a main PC it runs at your own risk.

## v1.0

First release of the Windows-native fork.

### Security
- Tunnel IP allowlist (default-deny); the "local" check ignores proxy/forwarding headers.
- Bypass permission mode is password-locked (separate from the login), auto-expires, and every restart, new chat and project switch returns to the safest mode.
- Generic sign-in page: no branding, no external requests.
- Prompt-injection hardening: external tool output is wrapped as `<untrusted_content>` (including the native Responses API path), memory never learns from it, and a secret bound to a host (`# hosts:` in the secrets file) is only ever sent to that host.
- Terminal Access plugin: authenticated, CSRF-protected, workspace-confined, command-screened, disabled by default.
- Controlled-shutdown chat persistence.

### Reliability
- Model calls time out by default and are limited per backend; a stall watchdog recovers hung jobs.
- No nested event loops (an agent could freeze permanently).
- Settings reads ~100x faster (no network call or git process per read).
- Time Travel snapshots serialized per repository; stale git locks cleared.
- Windows fixes: drive-letter paths in Document Query, no process-wide fake `fcntl`.

### WebUI
- New theme: accent colour with a themed colour picker, Solid/Glass/Enhanced materials, image or looping video wallpaper.
- Floating sidebar (edge tab to slide it away) and right-hand canvas; chat bubbles; accent buttons and toggles; composer actions bar that wraps cleanly; menus kept inside the viewport.
- Recently deleted chats (30-day trash) with Undo and Restore.
- Instant chat deletion.
- Plugins moved into the repository: Calendar, Personalities, Context Usage, Terminal Access.

### Project
- Removed upstream's Docker publishing and release automation; added a Windows test workflow.
- Test suite runs green on Windows; Linux/Docker-only tests are skipped via platform markers.
- Agent environment prompt and maintenance scripts use the real install path.
