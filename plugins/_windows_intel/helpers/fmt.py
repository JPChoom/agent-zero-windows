"""Turning query results into compact, capped text, and masking secrets.

Plain-text tables rather than JSON: roughly half the tokens, and easier for a
small local model to read. Pure functions, no Agent Zero imports.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

MASK = "<redacted>"

# Names whose *values* are secrets (environment variables, registry values,
# service parameters).
_SECRET_NAME = re.compile(
    r"pass(?:word|wd|phrase|code)?|pwd|secret|token|credential|api[_\-]?key|"
    r"private[_\-]?key|access[_\-]?key|auth(?:orization)?|session[_\-]?id|cookie|connection[_\-]?string",
    re.IGNORECASE,
)

_LABEL = r"(?:pass(?:word|wd|phrase|code)?|pwd|secret|token|api[_\-]?key|access[_\-]?key|client[_\-]?secret|auth(?:orization)?|bearer)"
_VALUE = r"(\"[^\"]*\"|'[^']*'|\S+)"
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Authorization: Bearer abc.def / Basic abc (before the label rule, which
    # would otherwise mask the word "Bearer" and leave the token)
    (re.compile(r"(\b(?:authorization:\s*)?(?:bearer|basic)\s+)[A-Za-z0-9._~+/=\-]{8,}", re.IGNORECASE), rf"\1{MASK}"),
    # --password hunter2 / -Password:hunter2 / /pass=hunter2
    (re.compile(rf"((?:^|\s)(?:--?|/){_LABEL}(?:\s*[=:]\s*|\s+)){_VALUE}", re.IGNORECASE), rf"\1{MASK}"),
    # password=hunter2 / token: abc / "api_key": "abc"
    (re.compile(rf"(\b{_LABEL}[\"']?\s*[=:]\s*)(?!(?:bearer|basic)\s){_VALUE}", re.IGNORECASE), rf"\1{MASK}"),
    # https://user:secret@host
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+(@)"), rf"\1{MASK}\2"),
    # well-known token shapes
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b"), MASK),
    (re.compile(r"\b(?:xox[abprs]|xapp)-[A-Za-z0-9\-]{10,}\b"), MASK),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), MASK),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), MASK),
]


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(str(name or "")))


def redact(text: Any) -> str:
    out = str(text if text is not None else "")
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def mask_value(name: str, value: Any) -> str:
    """The value, or a mask if its *name* says it is a secret; redacted either way."""
    if is_secret_name(name):
        return MASK
    return redact(value)


def cell(value: Any, width: int = 80) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[\r\n\t]+", " ", text).replace("|", "/").strip()
    text = re.sub(r" {2,}", " ", text)
    if len(text) > width:
        text = text[: max(1, width - 3)].rstrip() + "..."
    return text


def table(
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    limit: int,
    total: int | None = None,
    hint: str = "",
    max_chars: int = 12000,
    widths: dict[str, int] | None = None,
    default_width: int = 80,
) -> str:
    """Header + rows separated by ' | ', capped by row count and characters.

    `total` is how many rows matched before `limit`; the footer says what was
    left out and how to narrow the query.
    """
    widths = widths or {}
    rows = list(rows)
    shown = rows[:limit]
    total = len(rows) if total is None else total

    head = " | ".join(columns)
    lines = [head, "-" * min(len(head), 60)]
    used = sum(len(line) + 1 for line in lines)
    footer_reserve = 200
    emitted = 0
    for row in shown:
        line = " | ".join(
            cell(value, widths.get(columns[i], default_width) if i < len(columns) else default_width)
            for i, value in enumerate(row)
        )
        if used + len(line) + 1 > max_chars - footer_reserve:
            break
        lines.append(line)
        used += len(line) + 1
        emitted += 1

    if not emitted and not rows:
        lines.append("(none)")
    if emitted < total:
        reason = "output size cap" if emitted < len(shown) else f"limit {limit}"
        note = f"showing {emitted} of {total} ({reason})"
        if hint:
            note += f" - {hint}"
        lines.append(note)
    return "\n".join(lines)


def record(items: Iterable[tuple[str, Any]], *, max_chars: int = 12000, width: int = 200) -> str:
    """key: value lines for a single record."""
    out = [f"{key}: {cell(value, width)}" for key, value in items if value not in (None, "")]
    text = "\n".join(out)
    return text if len(text) <= max_chars else text[: max_chars - 40].rstrip() + "\n... (output size cap)"


def human_bytes(n: float | int | None) -> str:
    if n is None:
        return ""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return str(n)
