"""Every HTTP handler that skips the CSRF check is listed and justified here
(investigation finding F5). A new exemption fails this test until it is
reviewed: CSRF exemptions rely on SameSite=Lax session cookies, so an exempt
handler must either not use the session at all (API key, loopback, webhook
secret) or be safe to call.
"""

from __future__ import annotations

import glob
from pathlib import Path

from helpers.api import ApiHandler
from helpers.modules import load_classes_from_file

ROOT = Path(__file__).resolve().parents[1]

# (file, class): why it is exempt.
REVIEWED = {
    # API-key endpoints for external integrations: no session involved.
    ("api/api_files_get.py", "ApiFilesGet"): "API key",
    ("api/api_log_get.py", "ApiLogGet"): "API key",
    ("api/api_message.py", "ApiMessage"): "API key",
    ("api/api_reset_chat.py", "ApiResetChat"): "API key",
    ("api/api_terminate_chat.py", "ApiTerminateChat"): "API key",
    # Loopback-only maintenance calls (refused through the tunnel).
    ("api/cache_reset.py", "CacheReset"): "loopback only",
    ("api/scheduler_tick.py", "SchedulerTick"): "loopback only",
    # Read-only or session-ending.
    ("api/csrf_token.py", "GetCsrfToken"): "issues the token itself (GET)",
    ("api/health.py", "HealthCheck"): "read-only; details only for local callers",
    ("api/logout.py", "ApiLogout"): "only ends the session",
    ("api/rfc.py", "RFC"): "disabled on Windows (404)",
    ("plugins/_win_desktop/api/desktop_stream.py", "DesktopStream"): "read-only image stream for an <img> (GET)",
    ("plugins/_telegram_integration/api/webhook.py", "TelegramWebhook"): "webhook secret (constant-time)",
    # A0 CLI connector: session sign-in, protected by SameSite=Lax only.
    # Known gap (F5-b): a page on another localhost port is same-site. Needs
    # a CLI-side header or token before it can be closed.
    ("plugins/_a0_connector/api/v1/base.py", "PublicConnectorApiHandler"): "connector base",
    ("plugins/_a0_connector/api/v1/capabilities.py", "Capabilities"): "connector discovery, read-only",
    **{(f"plugins/_a0_connector/api/v1/{f}.py", c): "connector (F5-b)" for f, c in [
        ("agent_profile_set", "AgentProfileSet"), ("agents_list", "AgentsList"), ("browser_runtime", "BrowserRuntime"),
        ("chat_create", "ChatCreate"), ("chat_delete", "ChatDelete"), ("chat_get", "ChatGet"), ("chat_reset", "ChatReset"),
        ("chats_list", "ChatsList"), ("compact_chat", "CompactChat"), ("installed_plugins", "InstalledPlugins"),
        ("log_tail", "LogTail"), ("message_send", "MessageSend"), ("model_presets", "ModelPresets"),
        ("model_switcher", "ModelSwitcher"), ("nudge", "Nudge"), ("pause", "Pause"), ("projects", "Projects"),
        ("settings_get", "SettingsGet"), ("settings_set", "SettingsSet"), ("skills_activate", "SkillsActivate"),
        ("skills_delete", "SkillsDelete"), ("skills_list", "SkillsList"), ("token_status", "TokenStatus"),
    ]},
}


def _exempt_handlers() -> set[tuple[str, str]]:
    found = set()
    patterns = ("api/*.py", "plugins/*/api/*.py", "plugins/*/api/v1/*.py")
    for pattern in patterns:
        for path in glob.glob(str(ROOT / pattern)):
            rel = Path(path).relative_to(ROOT).as_posix()
            try:
                classes = load_classes_from_file(rel, ApiHandler)
            except Exception:
                continue
            for cls in classes:
                if not cls.requires_csrf():
                    found.add((rel, cls.__name__))
    return found


def test_every_csrf_exemption_is_reviewed():
    unreviewed = sorted(_exempt_handlers() - set(REVIEWED))
    assert unreviewed == [], (
        "These handlers skip the CSRF check but are not reviewed in tests/test_csrf_exemptions.py: "
        f"{unreviewed}. Add CSRF, or justify the exemption there."
    )


def test_exempt_handlers_without_session_auth_are_not_session_based():
    """An exempt handler that also skips session auth must be protected
    another way (API key, loopback, its own secret) or be harmless."""
    for rel, name in _exempt_handlers():
        assert (rel, name) in REVIEWED
