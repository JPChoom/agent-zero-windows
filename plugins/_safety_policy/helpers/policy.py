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
from urllib.parse import urlparse

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
    tier: str = "deny"  # "deny" or "approve" - meaningless when allowed=True
    # Populated whenever a "downloader"-category command was inspected,
    # regardless of the final allowed/denied outcome - advisory evidence
    # for the approval UI and audit trail, not itself a gate. See
    # classify_network_destination()'s docstring for what this can and
    # can't actually guarantee.
    network_destination: str = ""
    network_destination_allowed: bool | None = None


# Categories that require human approval rather than an unconditional deny,
# by default. These are context-dependent enough that a blanket deny would
# block real, occasionally-legitimate coding tasks (e.g. a project that
# genuinely needs a local test-only firewall rule) - unlike the categories
# left out of this set, which have no realistic legitimate use in a coding
# workflow (credential dumping, obfuscated PowerShell, disk formatting,
# registry/scheduled-task persistence) and stay hard-denied regardless of
# configuration intent, since a rushed Approve click under time pressure is
# a worse failure mode than just refusing outright. Overridable via the
# approval_categories argument (sourced from plugin config).
_APPROVAL_TIER_DEFAULT_CATEGORIES: frozenset[str] = frozenset(
    {"firewall_and_defender", "privilege_escalation", "account_changes"}
)


# First http(s) URL literal in the command text - not a real argument
# parser, just enough to find *a* URL regardless of which flag/position
# the different downloader tools put it in (curl/wget take it bare,
# Invoke-WebRequest/iwr use -Uri, Start-BitsTransfer uses -Source,
# certutil/bitsadmin take it as a positional arg after their own flags).
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>|&;]+", re.IGNORECASE)


def extract_network_destination(text: str) -> str:
    """Best-effort host extraction from the first http(s) URL literal in
    `text`, or "" if none is found or it doesn't parse. Purely textual -
    a URL built from a variable, string concatenation, or base64 evades
    this exactly like every other pattern in this file evades a
    determined adversarial payload. See README.md."""
    match = _URL_PATTERN.search(text)
    if not match:
        return ""
    try:
        host = urlparse(match.group(0)).hostname or ""
    except ValueError:
        return ""
    return host.lower()


def is_allowed_network_destination(host: str, allowlist) -> bool:
    """True if `host` is exactly an allowlisted entry, or a subdomain of
    one (api.github.com counts for an allowlisted github.com - the
    common CDN/API-subdomain pattern for these package registries)."""
    if not host:
        return False
    host = host.lower()
    normalized = {str(h).strip().lower() for h in (allowlist or []) if str(h).strip()}
    return any(host == d or host.endswith("." + d) for d in normalized)


def _match_builtin_categories(
    text: str,
    approval_categories,
    *,
    enable_network_allowlist: bool = False,
    network_allowlist=None,
) -> PolicyDecision:
    for category, patterns in _DENY_CATEGORIES.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if category == "downloader":
                    destination = extract_network_destination(text)
                    if destination:
                        dest_allowed = is_allowed_network_destination(destination, network_allowlist)
                        if enable_network_allowlist and dest_allowed:
                            # A command-text heuristic, not real network
                            # enforcement (see extract_network_destination's
                            # docstring) - but a fetch to a well-known
                            # package registry is common enough in normal
                            # coding work that treating it as a known-safe
                            # destination, rather than every curl/wget
                            # invocation needing a deny/approve decision
                            # regardless of where it points, is the actual
                            # point of having a configurable allowlist here.
                            return PolicyDecision(
                                allowed=True,
                                category=category,
                                network_destination=destination,
                                network_destination_allowed=True,
                            )
                        tier = "approve" if category in approval_categories else "deny"
                        return PolicyDecision(
                            allowed=False,
                            category=category,
                            pattern=pattern,
                            matched_text=match.group(0),
                            tier=tier,
                            network_destination=destination,
                            network_destination_allowed=dest_allowed,
                        )

                tier = "approve" if category in approval_categories else "deny"
                return PolicyDecision(
                    allowed=False,
                    category=category,
                    pattern=pattern,
                    matched_text=match.group(0),
                    tier=tier,
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


def classify_command(
    code: str,
    custom_patterns: list[str] | None = None,
    approval_categories=None,
    *,
    enable_network_allowlist: bool = False,
    network_allowlist=None,
) -> PolicyDecision:
    """Classify a terminal command. Returns allowed=False on the first
    matching deny pattern (built-in categories checked before custom
    ones); `decision.tier` is "approve" for categories in
    `approval_categories` (default: _APPROVAL_TIER_DEFAULT_CATEGORIES),
    "deny" for everything else including all custom-pattern matches.

    When a "downloader"-category command's URL resolves to a host on
    `network_allowlist` and `enable_network_allowlist` is set, the
    command is allowed outright instead of following the category's
    normal deny/approve tier - see _match_builtin_categories() and
    extract_network_destination()'s docstrings for what this check can
    and can't actually guarantee."""
    text = str(code or "")
    if not text.strip():
        return PolicyDecision(allowed=True)

    categories = (
        _APPROVAL_TIER_DEFAULT_CATEGORIES if approval_categories is None else approval_categories
    )
    decision = _match_builtin_categories(
        text, categories,
        enable_network_allowlist=enable_network_allowlist,
        network_allowlist=network_allowlist,
    )
    # decision.category truthy means a builtin category matched, even if
    # the network-allowlist auto-allow above turned that into
    # allowed=True - that decision (and its network_destination info)
    # must still be returned, not discarded in favor of a fresh
    # "nothing matched" custom-pattern check.
    if decision.category or not decision.allowed:
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


def classify_source_code(
    code: str,
    custom_patterns: list[str] | None = None,
    approval_categories=None,
    *,
    enable_network_allowlist: bool = False,
    network_allowlist=None,
) -> PolicyDecision:
    """Classify Python/Node.js source for the same command-line intents
    classify_command() denies for the terminal runtime, when they appear
    inside an actual shell-out call (os.system, subprocess.*,
    child_process.exec*/spawn*). `decision.tier` follows the same rule as
    classify_command()'s.

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

    categories = (
        _APPROVAL_TIER_DEFAULT_CATEGORIES if approval_categories is None else approval_categories
    )

    for call_match in _SHELLOUT_CALL_PATTERN.finditer(text):
        decision = _match_builtin_categories(
            call_match.group(1), categories,
            enable_network_allowlist=enable_network_allowlist,
            network_allowlist=network_allowlist,
        )
        # See classify_command()'s identical check: a builtin category
        # match that became allowed=True via the network-allowlist
        # auto-allow still needs to be returned, not treated the same as
        # "this call site matched nothing, keep scanning."
        if decision.category or not decision.allowed:
            return decision

    list_match = _SOURCE_LIST_ARG_DENY_PATTERN.search(text)
    if list_match:
        return PolicyDecision(
            allowed=False,
            category="shell_out_list_args",
            pattern=_SOURCE_LIST_ARG_DENY_PATTERN.pattern,
            matched_text=list_match.group(0),
            tier="deny",
        )

    # Custom patterns are hard denies; they take precedence over the
    # (possibly approve-tier) HTTP destination check.
    custom_decision = _match_custom_patterns(text, custom_patterns)
    if not custom_decision.allowed:
        return custom_decision

    http_decision = _classify_source_http(text, categories, enable_network_allowlist, network_allowlist)
    if http_decision is not None:
        return http_decision

    return custom_decision


# Python/Node HTTP clients. Downloads made from inside a script never pass a
# curl/wget command line, so the downloader category used to miss them
# entirely. Scripts usually keep the host in a constant
# (BASE = "https://...") and build request URLs from it, so rather than only
# matching a URL literal at the call site, any http(s) literal anywhere in a
# source that uses an HTTP client is treated as a destination.
_SOURCE_HTTP_CLIENT_PATTERN = re.compile(
    r"\b(?:requests\.(?:get|post|put|patch|delete|head|request|Session)"
    r"|httpx\.|aiohttp\.|urllib\.request|urlopen|urlretrieve|http\.client"
    r"|fetch\s*\(|axios\b|got\s*\(|node-fetch|https?\.get\s*\(|https?\.request\s*\()",
    re.IGNORECASE,
)


def _classify_source_http(text, approval_categories, enable_network_allowlist, network_allowlist):
    client = _SOURCE_HTTP_CLIENT_PATTERN.search(text)
    if not client:
        return None
    hosts: list[str] = []
    for match in _URL_PATTERN.finditer(text):
        try:
            host = (urlparse(match.group(0)).hostname or "").lower()
        except ValueError:
            continue
        if host and host not in hosts:
            hosts.append(host)
    if not hosts:
        return None  # URL built at runtime - nothing textual to judge (see README)

    blocked = [h for h in hosts if not (enable_network_allowlist and is_allowed_network_destination(h, network_allowlist))]
    if not blocked:
        return PolicyDecision(
            allowed=True,
            category="downloader",
            network_destination=hosts[0],
            network_destination_allowed=True,
        )
    tier = "approve" if "downloader" in approval_categories else "deny"
    return PolicyDecision(
        allowed=False,
        category="downloader",
        pattern=_SOURCE_HTTP_CLIENT_PATTERN.pattern,
        matched_text=client.group(0),
        tier=tier,
        network_destination=blocked[0],
        network_destination_allowed=False,
    )
