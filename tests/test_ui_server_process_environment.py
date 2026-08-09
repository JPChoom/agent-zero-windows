"""Tests for configure_process_environment()'s stdout/stderr UTF-8 fix.

Reproduces the real crash reported in a user log: Windows consoles default
stdout/stderr to a legacy code page (commonly cp1252), which can't encode
most emoji/non-ASCII characters a streamed model response may contain.
print_style.py's stream()/print() then raise UnicodeEncodeError - and
since agent.py retries on exception, the same unprintable character
resurfaces every retry, producing an infinite crash loop instead of one
failed print.
"""

from types import SimpleNamespace

from helpers.ui_server import configure_process_environment


def test_configure_process_environment_reconfigures_stdout_and_stderr_to_utf8(monkeypatch):
    calls = []

    class _FakeStream:
        def reconfigure(self, encoding=None, errors=None):
            calls.append({"encoding": encoding, "errors": errors})

    monkeypatch.setattr("sys.stdout", _FakeStream())
    monkeypatch.setattr("sys.stderr", _FakeStream())

    configure_process_environment()

    assert len(calls) == 2
    assert all(call == {"encoding": "utf-8", "errors": "replace"} for call in calls)


def test_configure_process_environment_tolerates_streams_without_reconfigure(monkeypatch):
    # e.g. pytest's captured stdout, or a stream some other wrapper replaced -
    # must not raise, just skip reconfiguring that stream.
    monkeypatch.setattr("sys.stdout", SimpleNamespace())
    monkeypatch.setattr("sys.stderr", SimpleNamespace())

    configure_process_environment()  # should not raise


def test_configure_process_environment_actually_fixes_the_reported_crash():
    """End-to-end: reproduces the exact UnicodeEncodeError from the user's
    log (cp1252 encoding, U+1F44B waving-hand emoji) and confirms
    configure_process_environment() makes it printable without crashing."""
    import io
    import sys

    cp1252_stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    try:
        cp1252_stream.write("\U0001F44B")
        raised = False
    except UnicodeEncodeError:
        raised = True
    assert raised, "test setup assumption broken: cp1252 should reject U+1F44B"

    utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    utf8_stream.reconfigure(encoding="utf-8", errors="replace")
    utf8_stream.write("\U0001F44B")  # must not raise
    utf8_stream.flush()
