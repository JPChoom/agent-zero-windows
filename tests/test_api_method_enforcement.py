"""The dispatcher must enforce get_methods() on every request.

Found live: api/csrf_token.py declares get_methods() -> ["GET"], yet a POST
to /api/csrf_token returned a token. The method check ran only on the
cache-miss path, so the first request for a path cached the wrapped
handler and every later request - any method - was served straight from
the cache with no check at all.

That is method confusion: a GET-only endpoint answering POSTs for as long
as the cache stays warm, and the symptom is invisible because it depends
on whether something warmed the cache first. It surfaced here as a POST
that worked before a restart and 405'd after one.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _dispatch_source() -> str:
    text = (PROJECT_ROOT / "helpers" / "api.py").read_text(encoding="utf-8")
    start = text.index("async def _dispatch(")
    end = text.index("app.add_url_rule(", start)
    return text[start:end]


def test_the_cached_path_checks_the_method():
    """The regression: a cache hit returned the handler without ever
    looking at request.method."""
    body = _dispatch_source()
    cached_branch = body.split("cached = cache.get(", 1)[1].split("# Resolve", 1)[0]
    assert "request.method" in cached_branch, (
        "a cache hit must validate the method; without this any endpoint "
        "accepts any method once its handler has been cached"
    )


def test_the_cache_stores_the_allowed_methods():
    """The check on the hit path needs the methods, so they have to be
    cached with the handler rather than recomputed from a class the hit
    path never loads."""
    body = _dispatch_source()
    assert "cache.add(CACHE_AREA, path, (methods, handler_fn))" in body


def test_the_miss_path_still_checks():
    body = _dispatch_source()
    assert "methods = handler_cls.get_methods()" in body
    assert "if request.method not in methods:" in body


def test_csrf_token_is_still_declared_get_only():
    """This is the endpoint the bug was found on. If it ever becomes
    POST-able by declaration, the finding above changes meaning."""
    from api.csrf_token import GetCsrfToken

    assert GetCsrfToken.get_methods() == ["GET"]


def test_both_paths_reject_through_the_same_helper():
    """One place that builds the 405, so the two paths cannot drift into
    disagreeing about what a refusal looks like."""
    body = _dispatch_source()
    assert body.count("_method_not_allowed(path)") >= 2
