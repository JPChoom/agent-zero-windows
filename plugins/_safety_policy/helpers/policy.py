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


def _match_builtin_categories(text: str) -> PolicyDecision:
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
    return PolicyDecision(allowed=True)


def _match_custom_patterns(text: str, custom_patterns: list[str] | None) -> PolicyDecision:
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


def classify_command(code: str, custom_patterns: list[str] | None = None) -> PolicyDecision:
    """Classify a terminal command. Returns allowed=False on the first
    matching deny pattern (built-in categories checked before custom ones)."""
    text = str(code or "")
    if not text.strip():
        return PolicyDecision(allowed=True)

    decision = _match_builtin_categories(text)
    if not decision.allowed:
        return decision

    return _match_custom_patterns(text, custom_patterns)


# Names of shell-out functions Python/Node.js code uses to run an external
# command - matched both fully-qualified (os.system(...),
# subprocess.run(...), child_process.execSync(...)) and bare (execSync(...)),
# since destructuring the import ("const { execSync } = require(...)") is at
# least as common in real Node.js code as the qualified form, and would
# otherwise evade a prefix-anchored pattern entirely.
_SHELLOUT_CALL_PATTERN = re.compile(
    r"\b(?:os\.system|os\.popen"
    r"|subprocess\.(?:run|call|check_call|check_output|Popen)"
    r"|(?:child_process\.)?(?:exec|execSync|spawn|spawnSync|execFile|execFileSync))"
    r"\s*\((.{0,400}?)\)",
    re.IGNORECASE | re.DOTALL,
)

# A dangerous executable passed as the first argument to a shell-out call in
# Python's list-args form (subprocess.run(["reg", "add", ...])) or Node's
# (command, argsArray) form (spawn("reg", ["add", ...])) never appears as
# one contiguous "reg add" string the way classify_command()'s patterns
# expect - each token is a separate, quote-delimited list element. Matched
# directly against the full source (not just captured call args) since it's
# already anchored to a real call site immediately before the token.
_SOURCE_LIST_ARG_DENY_PATTERN = re.compile(
    r"\b(?:subprocess\.(?:run|call|check_call|check_output|Popen)"
    r"|(?:child_process\.)?(?:spawn|spawnSync|execFile|execFileSync))"
    r"\s*\(\s*\[?\s*['\"](?:reg|schtasks|sc|vssadmin|netsh|runas|shutdown|format|diskpart"
    r"|bcdedit|net|mimikatz|procdump|certutil|bitsadmin)(?:\.exe)?['\"]",
    re.IGNORECASE,
)


def classify_source_code(code: str, custom_patterns: list[str] | None = None) -> PolicyDecision:
    """Classify Python/Node.js source for the same command-line intents
    classify_command() denies for the terminal runtime, when they appear
    inside an actual shell-out call (os.system, subprocess.*,
    child_process.exec*/spawn*).

    Deliberately does NOT scan the whole source with classify_command()'s
    patterns directly - several of them are common English/programming
    words (format, credential) that would false-positive constantly on
    ordinary code (str.format(), a "credentials" variable, ...). Scoping to
    the text passed to a real shell-out call keeps that risk low without
    losing the coverage that matters: an agent asked to do something
    destructive most naturally reaches for the same command syntax it
    already knows from the terminal runtime.

    Still not a static analyzer: indirection (building the command string
    from variables, string concatenation, base64, calling a shell-out
    function through an alias/wrapper) evades this the same way it evades
    classify_command() for literal terminal commands. See README.md.
    """
    text = str(code or "")
    if not text.strip():
        return PolicyDecision(allowed=True)

    for call_match in _SHELLOUT_CALL_PATTERN.finditer(text):
        decision = _match_builtin_categories(call_match.group(1))
        if not decision.allowed:
            return decision

    list_match = _SOURCE_LIST_ARG_DENY_PATTERN.search(text)
    if list_match:
        return PolicyDecision(
            allowed=False,
            category="shell_out_list_args",
            pattern=_SOURCE_LIST_ARG_DENY_PATTERN.pattern,
            matched_text=list_match.group(0),
        )

    return _match_custom_patterns(text, custom_patterns)
