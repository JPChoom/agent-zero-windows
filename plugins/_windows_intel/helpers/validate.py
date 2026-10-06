"""Argument validation for windows_info: the only way model-supplied text
reaches a source. Everything is checked against helpers/schema.py; anything
unknown, malformed or oversized is rejected with a message the model can act
on. Pure functions, no Agent Zero imports.
"""

from __future__ import annotations

import re

from plugins._windows_intel.helpers.schema import ACTIONS, Arg

# Names of processes, services, logs, providers, device classes: no quotes,
# backticks, dollar signs, semicolons, pipes or control characters.
NAME_RE = re.compile(r"^[A-Za-z0-9 ._\-/()+:@#]{1,100}$")
_REG_ROOTS = {
    "HKLM": "HKLM", "HKEY_LOCAL_MACHINE": "HKLM",
    "HKCU": "HKCU", "HKEY_CURRENT_USER": "HKCU",
}
_REG_BAD = re.compile(r"[\x00-\x1f\"<>|*?]")
_DURATION_RE = re.compile(r"^(\d{1,3})\s*([mhdw])$", re.IGNORECASE)
_DURATION_HOURS = {"m": 1 / 60, "h": 1.0, "d": 24.0, "w": 168.0}
MAX_DURATION_HOURS = 90 * 24.0
_TRUE = {"true", "yes", "1", "on", "y"}
_FALSE = {"false", "no", "0", "off", "n"}


def normalize_action(action) -> str:
    return str(action or "").strip().lower().replace("-", "_")


def _bad_chars(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def _coerce(name: str, spec: Arg, value, max_limit: int):
    kind = spec.kind
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"{name} must be true or false")

    if kind == "int":
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a whole number")
        try:
            number = int(str(value).strip(), 10)
        except ValueError:
            raise ValueError(f"{name} must be a whole number")
        lo, hi = spec.lo, spec.hi or max_limit
        if name == "limit" and spec.hi:
            hi = min(spec.hi, max_limit)
        if not lo <= number <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        return number

    text = str(value).strip() if value is not None else ""
    if kind == "enum":
        low = text.lower()
        if low not in spec.choices:
            raise ValueError(f"{name} must be one of: {', '.join(spec.choices)}")
        return low

    if kind == "name":
        if not NAME_RE.match(text):
            raise ValueError(
                f"{name} may only contain letters, digits, spaces and . _ - / ( ) + : @ # (1-100 characters)"
            )
        return text

    if kind == "duration":
        match = _DURATION_RE.match(text)
        if not match:
            raise ValueError(f"{name} must look like 30m, 24h, 7d or 2w")
        hours = int(match.group(1)) * _DURATION_HOURS[match.group(2).lower()]
        if not 0 < hours <= MAX_DURATION_HOURS:
            raise ValueError(f"{name} must be between 1 minute and 90 days")
        return hours

    if kind == "regpath":
        return normalize_registry_path(text)

    if kind == "regvalue":
        if not text or len(text) > 260 or _bad_chars(text):
            raise ValueError(f"{name} must be a registry value name (up to 260 printable characters)")
        return text

    raise ValueError(f"unsupported argument type for {name}")


def normalize_registry_path(path: str) -> str:
    """HKLM\\... form; accepts HKLM:\\, HKEY_LOCAL_MACHINE\\ and forward slashes."""
    text = str(path or "").strip().replace("/", "\\")
    text = re.sub(r"^(Registry::)", "", text, flags=re.IGNORECASE)
    root, _, rest = text.partition("\\")
    root = root.rstrip(":").upper()
    if root not in _REG_ROOTS:
        raise ValueError("path must start with HKLM or HKCU (HKEY_LOCAL_MACHINE / HKEY_CURRENT_USER also work)")
    rest = rest.strip("\\")
    if len(rest) > 400 or _REG_BAD.search(rest) or any(part == ".." for part in rest.split("\\")):
        raise ValueError("path contains characters that are not valid in a registry key path")
    return _REG_ROOTS[root] + ("\\" + rest if rest else "")


def validate(action, raw_args: dict | None, *, default_limit: int = 50, max_limit: int = 500) -> tuple[str, dict]:
    """Return (action, clean args with defaults), or raise ValueError."""
    action = normalize_action(action)
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; use one of: {', '.join(ACTIONS)}")
    spec_args = ACTIONS[action].args
    raw_args = dict(raw_args or {})

    unknown = [k for k in raw_args if k not in spec_args]
    if unknown:
        allowed = ", ".join(spec_args) or "none"
        raise ValueError(f"{action} does not take {', '.join(map(repr, unknown))}; allowed arguments: {allowed}")

    clean: dict = {}
    for name, spec in spec_args.items():
        value = raw_args.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if spec.required:
                raise ValueError(f"{action} needs {name}")
            default = spec.default
            if name == "limit" and spec.kind == "int" and spec.default is None:
                default = min(default_limit, max_limit)
            if default is not None:
                clean[name] = default
            continue
        clean[name] = _coerce(name, spec, value, max_limit)
    return action, clean
