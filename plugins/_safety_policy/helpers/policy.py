"""Deterministic command policy classifier for the terminal runtime.

Extends the deny-pattern approach already used by the separate, disabled-by-
default usr/plugins/terminal_access plugin (helpers/safe_executor.py) - that
plugin guards a different host-execution surface, so the patterns are
reproduced and extended here rather than imported (a hard dependency on a
user-customizable/possibly-absent plugin would be fragile), covering the
categories it doesn't: BITS downloads, firewall/Defender changes, privilege
escalation, account changes, shadow-copy deletion, and Invoke-Expression.

This is regex/substring matching on the literal command text, not a real
PowerShell parser - it catches the obvious, common cases and is explicitly
NOT a sandbox. A determined adversarial payload can still evade it (string
concatenation, variable indirection, alternate aliases). See README.md.
"""

import re
from dataclasses import dataclass

# Each category maps to a list of patterns. All patterns are compiled
# case-insensitive. Keep category names short and stable - they show up in
# the denial message the agent sees.
_DENY_CATEGORIES: dict[str, tuple[str, ...]] = {
    "downloader": (
        r"\b(?:invoke-webrequest|iwr|curl|wget|certutil|bitsadmin)\b",
        r"\bstart-bitstransfer\b",
    ),
    "persistence": (
        r"\b(?:reg(?:\.exe)?\s+(?:add|import)|schtasks|sc(?:\.exe)?\s+create|new-service)\b",
        r"\b(?:new-scheduledtask|register-scheduledtask)\b",
    ),
    "credential_access": (
        r"\b(?:mimikatz|procdump|sekurlsa|credential)\b",
    ),
    "obfuscation": (
        r"\b(?:encodedcommand|frombase64string)\b",
        # "-enc" starts with a non-word char, so a leading \b is never true
        # here (no boundary exists between a preceding space and a hyphen);
        # match "not preceded by a non-whitespace char" instead.
        r"(?<!\S)-enc\b",
        r"\b(?:invoke-expression|iex)\b",
    ),
    "destructive_delete": (
        r"\b(?:remove-item|del|erase|rd|rmdir)\b[^\r\n]*(?:\\windows|\\program files|\\users\\[^\\]+\\(?:appdata|ntuser))",
    ),
    "disk_and_reboot": (
        r"\b(?:shutdown|restart-computer|stop-computer|format|diskpart|bcdedit)\b",
        r"\bvssadmin\b[^\r\n]*\bdelete\b",
    ),
    "firewall_and_defender": (
        r"\b(?:new-netfirewallrule|remove-netfirewallrule|set-mppreference|add-mppreference)\b",
        r"\bnetsh\b[^\r\n]*\badvfirewall\b",
    ),
    "privilege_escalation": (
        r"\brunas(?:\.exe)?\b",
        r"\bstart-process\b[^\r\n]*-verb\s+runas",
    ),
    "account_changes": (
        r"\bnet\s+(?:user|localgroup)\b",
        r"\b(?:new-localuser|add-localgroupmember)\b",
    ),
}


@dataclass
class PolicyDecision:
    allowed: bool
    category: str = ""
    pattern: str = ""
    matched_text: str = ""
    custom: bool = False


def classify_command(code: str, custom_patterns: list[str] | None = None) -> PolicyDecision:
    """Classify a terminal command. Returns allowed=False on the first
    matching deny pattern (built-in categories checked before custom ones)."""
    text = str(code or "")
    if not text.strip():
        return PolicyDecision(allowed=True)

    for category, patterns in _DENY_CATEGORIES.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return PolicyDecision(
                    allowed=False,
                    category=category,
                    pattern=pattern,
                    matched_text=match.group(0),
                )

    for pattern in custom_patterns or []:
        pattern = str(pattern or "").strip()
        if not pattern:
            continue
        try:
            match = re.search(pattern, text, re.IGNORECASE)
        except re.error:
            continue  # invalid user-supplied regex - skip rather than fail closed on a typo
        if match:
            return PolicyDecision(
                allowed=False,
                category="custom",
                pattern=pattern,
                matched_text=match.group(0),
                custom=True,
            )

    return PolicyDecision(allowed=True)
