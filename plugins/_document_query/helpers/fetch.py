"""Centralized document fetching for the document_query plugin."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

import aiohttp

from helpers import files


InterventionCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class FetchedDocument:
    """Fetched document bytes plus metadata needed by parsers."""

    uri: str
    scheme: str
    mimetype: str
    content: bytes
    encoding: str | None = None
    charset: str | None = None
    local_path: str | None = None
    source_uri: str | None = None

    def text(self) -> str:
        charset = self.charset or "utf-8"
        return self.content.decode(charset, errors="replace")

    def suffix(self) -> str:
        path = self.local_path or urlparse(self.uri).path or self.uri
        suffix = Path(path).suffix
        if suffix:
            return suffix
        guessed = mimetypes.guess_extension(self.mimetype)
        return guessed or ".bin"

    @contextmanager
    def local_file(self):
        """Yield a filesystem path for parsers that cannot consume bytes."""
        if self.local_path and os.path.exists(self.local_path):
            yield self.local_path
            return

        tmp = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=self.suffix()) as f:
                f.write(self.content)
                tmp = f.name
            yield tmp
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


ProtocolHandler = Callable[
    [str, str, dict, InterventionCallback | None], Awaitable[FetchedDocument]
]

_PROTOCOL_HANDLERS: dict[str, ProtocolHandler] = {}

_WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def register_protocol_handler(scheme: str, handler: ProtocolHandler) -> None:
    """Register or replace a fetch handler for a URI scheme."""
    _PROTOCOL_HANDLERS[scheme.lower()] = handler


async def fetch_public_resource(
    uri: str,
    config: dict | None = None,
    intervention_callback: InterventionCallback | None = None,
) -> FetchedDocument:
    """Fetch local or remote content once, then pass bytes to parsers."""
    config = config or {}
    parsed = urlparse(uri)
    scheme = (parsed.scheme or "file").lower()
    # urlparse reads a Windows drive letter ("C:\docs\a.pdf", "c:/docs") as a
    # one-letter scheme; drive and UNC paths are local files.
    if _WINDOWS_PATH.match(uri):
        scheme = "file"
    handler = _PROTOCOL_HANDLERS.get(scheme)
    if not handler:
        raise ValueError(f"Unsupported document scheme: {scheme}")
    return await handler(uri, scheme, config, intervention_callback)


async def _fetch_file(
    uri: str,
    scheme: str,
    config: dict,
    intervention_callback: InterventionCallback | None,
) -> FetchedDocument:
    parsed = urlparse(uri)
    raw_path = parsed.path if parsed.scheme == "file" else uri
    if not raw_path:
        raise ValueError(f"Invalid document path: {uri}")

    path = _fix_file_path(raw_path)
    mimetype, encoding = mimetypes.guess_type(path)
    if encoding:
        raise ValueError(f"Compressed documents are unsupported '{encoding}' ({uri})")
    mimetype = mimetype or "application/octet-stream"
    if mimetype == "application/octet-stream":
        raise ValueError(f"Unsupported document mimetype '{mimetype}' ({uri})")

    if intervention_callback:
        await intervention_callback()
    return FetchedDocument(
        uri=path,
        source_uri=uri,
        scheme=scheme,
        mimetype=mimetype,
        encoding=encoding,
        content=files.read_file_bin(path),
        local_path=path,
    )


async def _fetch_http(
    uri: str,
    scheme: str,
    config: dict,
    intervention_callback: InterventionCallback | None,
) -> FetchedDocument:
    timeout = float(config.get("fetch_timeout", 30))
    retries = max(1, int(config.get("fetch_retries", 3)))
    retry_backoff = float(config.get("fetch_retry_backoff", 1.0))
    max_remote_bytes = int(config.get("max_remote_bytes", 50 * 1024 * 1024))
    parsed = urlparse(uri)
    guessed_mimetype, encoding = mimetypes.guess_type(parsed.path or uri)
    if encoding:
        raise ValueError(f"Compressed documents are unsupported '{encoding}' ({uri})")

    last_error = ""
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(uri, allow_redirects=True) as response:
                    if response.status > 399:
                        raise ValueError(f"HTTP {response.status}")

                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_remote_bytes:
                        size_mb = int(content_length) / 1024 / 1024
                        raise ValueError(
                            f"Document exceeds max {max_remote_bytes / 1024 / 1024:.0f}MB: "
                            f"{size_mb:.2f} MB ({uri})"
                        )

                    chunks: list[bytes] = []
                    downloaded = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        downloaded += len(chunk)
                        if downloaded > max_remote_bytes:
                            size_mb = downloaded / 1024 / 1024
                            raise ValueError(
                                f"Document exceeds max {max_remote_bytes / 1024 / 1024:.0f}MB: "
                                f"{size_mb:.2f} MB ({uri})"
                            )
                        chunks.append(chunk)
                        if intervention_callback:
                            await intervention_callback()

                    content_type = response.headers.get("content-type", "")
                    mimetype, charset = _parse_content_type(content_type)
                    if not mimetype or mimetype == "application/octet-stream":
                        mimetype = guessed_mimetype or "application/octet-stream"
                    if mimetype == "application/octet-stream":
                        raise ValueError(
                            f"Unsupported document mimetype '{mimetype}' ({uri})"
                        )

                    fetched = FetchedDocument(
                        uri=str(response.url),
                        source_uri=uri,
                        scheme=response.url.scheme or scheme,
                        mimetype=mimetype,
                        encoding=encoding,
                        charset=charset,
                        content=b"".join(chunks),
                    )
                    if mimetype == "text/html" and _looks_like_bot_wall(fetched.text()):
                        if intervention_callback:
                            await intervention_callback()
                        browser_fetched = await _fetch_via_browser(str(response.url))
                        if browser_fetched and len(browser_fetched.content) > len(fetched.content):
                            return browser_fetched
                    return fetched
        except Exception as e:
            last_error = str(e)
            if attempt < retries - 1:
                await asyncio.sleep(retry_backoff)
                if intervention_callback:
                    await intervention_callback()

    raise ValueError(f"Document fetch error: {uri} ({last_error})")


def _parse_content_type(value: str) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    parts = [part.strip() for part in value.split(";") if part.strip()]
    mimetype = parts[0].lower() if parts else None
    charset = None
    for part in parts[1:]:
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip("\"'")
            break
    return mimetype, charset


register_protocol_handler("file", _fetch_file)
register_protocol_handler("http", _fetch_http)
register_protocol_handler("https", _fetch_http)


# Sites like reddit.com serve a JS-driven bot-challenge shell to a plain
# aiohttp GET (no navigator.webdriver spoofing, no JS execution) instead of
# real content - the direct fetch above "succeeds" (200 OK) but the body is
# just the challenge page. Detected by a short, marker-bearing body; when
# triggered, retried once through the internal Playwright browser (the same
# runtime plugins/_browser already hardens against this - see
# plugins/_browser/helpers/config.py), which executes the challenge JS like
# a real browser would. Falls back to the original fetch result if the
# browser retry doesn't actually produce more content, so this can only
# help, never make an already-working fetch worse.
_BOT_WALL_MAX_VISIBLE_CHARS = 200
_BOT_WALL_MARKERS = (
    "prove your humanity",
    "just a moment",
    "checking your browser",
    "enable javascript and cookies",
    "verify you are human",
    "cf-turnstile",
    "cf_chl",
    "captcha",
    "access denied",
)
_SCRIPT_OR_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _visible_text_from_html(html: str) -> str:
    """Crude but effective for this heuristic: strip <script>/<style> blocks
    and remaining tags to approximate what a reader would actually see -
    NOT a real HTML parser, just enough to tell "an article" apart from
    "a JS challenge shell whose visible content is a two-word title"."""
    without_code = _SCRIPT_OR_STYLE_RE.sub(" ", html)
    without_tags = _TAG_RE.sub(" ", without_code)
    return _WHITESPACE_RE.sub(" ", without_tags).strip()


def _looks_like_bot_wall(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if any(marker in lowered for marker in _BOT_WALL_MARKERS):
        return True
    # Raw HTML length says nothing here - a challenge shell can carry
    # several KB of JS/CSS boilerplate while showing the reader almost
    # nothing. Strip it down to visible text and judge that instead.
    return len(_visible_text_from_html(stripped)) < _BOT_WALL_MAX_VISIBLE_CHARS


async def _fetch_via_browser(uri: str) -> FetchedDocument | None:
    """Best-effort retry of `uri` through the internal browser runtime.
    Returns None on any failure - this is a fallback, never the primary
    path, so it must never itself raise or block a document fetch."""
    import uuid

    from plugins._browser.helpers import runtime as browser_runtime

    context_id = f"_document_query_fetch_{uuid.uuid4().hex}"
    try:
        runtime = await browser_runtime.get_runtime(context_id, create=True)
        if runtime is None:
            return None
        await runtime.call("open", uri)
        await asyncio.sleep(3)  # let any JS challenge/redirect resolve
        content = await runtime.call("content", None, None)
        text = content.get("document", "") if isinstance(content, dict) else str(content)
        if not text or not text.strip():
            return None
        return FetchedDocument(
            uri=uri,
            source_uri=uri,
            scheme="https",
            mimetype="text/plain",
            charset="utf-8",
            content=text.encode("utf-8"),
        )
    except Exception:
        return None
    finally:
        try:
            await browser_runtime.close_runtime(context_id, delete_profile=True)
        except Exception:
            pass


def _fix_file_path(path: str) -> str:
    if os.path.isabs(path) and os.path.exists(path):
        return path
    return files.fix_dev_path(path)
