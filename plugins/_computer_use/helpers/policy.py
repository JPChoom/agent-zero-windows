"""Hard limits for computer_use that no permission mode lifts.

Pure functions (no Agent Zero or driver imports) so they are unit-tested
directly. The tool calls them before every action; a refusal here is final
and is not turned into an approval prompt.
"""

from __future__ import annotations

import re

# Actions that only look. Everything else changes the desktop.
READ_ACTIONS = frozenset({"apps", "windows", "inspect", "screenshot", "status"})

# Actions that send input into a window.
INPUT_ACTIONS = frozenset({"type", "key", "hotkey", "set_value"})

# Windows that authenticate the user, elevate privileges or hold secrets.
# Nothing - not even reading their UI tree - is allowed there.
SECRET_PROCESSES = frozenset({
    "consent.exe",              # UAC prompt
    "credentialuibroker.exe",   # Windows credential dialog
    "logonui.exe",
    "lockapp.exe",
    "keepass.exe",
    "keepassxc.exe",
    "1password.exe",
    "bitwarden.exe",
    "dashlane.exe",
    "enpass.exe",
    "proton pass.exe",
})

# Shells and terminals. Typing into them would run commands without the
# command safety floor (_safety_policy) ever seeing the text - the agent
# must use its terminal tool instead.
TERMINAL_PROCESSES = frozenset({
    "windowsterminal.exe", "wt.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "conhost.exe", "openconsole.exe", "mintty.exe",
    "alacritty.exe", "wezterm-gui.exe", "putty.exe", "powershell_ise.exe",
})

# Key combinations that lock, log off, open a run box or the security
# screen. Never sent.
_BLOCKED_HOTKEYS = [
    {"win", "l"},
    {"ctrl", "alt", "delete"},
    {"ctrl", "alt", "del"},
    {"win", "r"},
    {"win", "x"},
    {"ctrl", "shift", "esc"},
]

# Allowed, but always asked about (can close a window with unsaved work).
_ASK_HOTKEYS = [{"alt", "f4"}, {"ctrl", "w"}, {"ctrl", "q"}]

_KEY_ALIASES = {
    "control": "ctrl", "cmd": "win", "super": "win", "meta": "win",
    "windows": "win", "escape": "esc", "option": "alt", "return": "enter",
}

_SECRET_LABEL = re.compile(
    r"pass(word|code|phrase)|\bpin\b|\botp\b|one[- ]time|2fa|two[- ]factor|"
    r"security code|secret|recovery (key|code)|cvv|card number",
    re.IGNORECASE,
)


def normalize_keys(keys) -> list[str]:
    if isinstance(keys, str):
        keys = re.split(r"[+\s,]+", keys)
    out = []
    for k in keys or []:
        k = str(k).strip().lower()
        if k:
            out.append(_KEY_ALIASES.get(k, k))
    return out


def blocked_hotkey(keys) -> str:
    combo = set(normalize_keys(keys))
    for blocked in _BLOCKED_HOTKEYS:
        if combo == blocked:
            return "+".join(sorted(blocked))
    return ""


def risky_hotkey(keys) -> bool:
    combo = set(normalize_keys(keys))
    return any(combo == risky for risky in _ASK_HOTKEYS)


def is_secret_label(label: str) -> bool:
    return bool(_SECRET_LABEL.search(str(label or "")))


def refusal(action: str, process_name: str = "", keys=None, element_label: str = "") -> str:
    """Return a refusal message, or "" if the action may proceed."""
    proc = str(process_name or "").strip().lower()
    if proc in SECRET_PROCESSES:
        return (
            f"{proc} handles sign-in, elevation or stored secrets; computer_use never "
            "reads or acts on it. Ask the user to do this step themselves."
        )
    if action in INPUT_ACTIONS and proc in TERMINAL_PROCESSES:
        return (
            f"{proc} is a terminal; typing into it would bypass the command safety "
            "policy. Use the code execution tool instead."
        )
    if action == "hotkey":
        blocked = blocked_hotkey(keys)
        if blocked:
            return f"The key combination {blocked} (lock, log off, run box or security screen) is never sent."
    if action in ("type", "set_value") and is_secret_label(element_label):
        return (
            f"The target field looks like a secret ({element_label!r}). The agent never "
            "enters passwords, PINs or codes; ask the user to type it."
        )
    return ""
