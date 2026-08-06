from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from helpers.errors import RepairableException


_SPECIAL_SCHEME_RE = re.compile(r"^(?:about|blob|data|file|mailto|tel):", re.I)
_URL_SCHEME_RE = re.compile(r"^[a-z][a-z\d+\-.]*://", re.I)
_LOCAL_HOST_RE = re.compile(
    r"^(?:localhost|\[[0-9a-f:.]+\]|(?:\d{1,3}\.){3}\d{1,3})(?::\d+)?$",
    re.I,
)
_TYPED_HOST_RE = re.compile(
    r"^(?:localhost|\[[0-9a-f:.]+\]|(?:\d{1,3}\.){3}\d{1,3}|"
    r"(?:[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?\.)+[a-z\d-]{2,63})(?::\d+)?$",
    re.I,
)


def normalize_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Browser navigation requires a non-empty URL.")
    if raw.startswith(("/", "?", "#", ".")):
        raise RepairableException(
            f"Browser navigation target {raw!r} is relative; provide a full URL with a scheme."
        )

    def with_trailing_path(url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme in {"http", "https"} and not parts.path:
            return urlunsplit((parts.scheme, parts.netloc, "/", parts.query, parts.fragment))
        return urlunsplit(parts)

    try:
        host = re.split(r"[/?#]", raw, maxsplit=1)[0] or ""
        if (
            not _URL_SCHEME_RE.match(raw)
            and not _SPECIAL_SCHEME_RE.match(raw)
            and not raw.startswith(("/", "?", "#", "."))
            and not re.search(r"\s", raw)
            and _TYPED_HOST_RE.match(host)
        ):
            protocol = "http://" if _LOCAL_HOST_RE.match(host) else "https://"
            return with_trailing_path(protocol + raw)

        parts = urlsplit(raw)
        if parts.scheme:
            return with_trailing_path(raw)
    except Exception:
        pass

    return with_trailing_path("https://" + raw)
