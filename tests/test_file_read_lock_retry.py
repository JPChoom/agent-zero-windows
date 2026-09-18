"""helpers.files._read_with_lock_retry absorbs a transient Windows
file-lock error on plain file reads, instead of surfacing it for
something that would have succeeded on the very next attempt.

Observed live at server startup: real PermissionError (WinError 5)
failures reading several unrelated files within moments of each other -
a core prompt template (agent.system.main.role.md), a scheduler
tasks.json, a plugin's default_config.yaml - each readable again
immediately after, confirming a transient OS-level lock (Windows
Defender / the search indexer briefly holding a just-touched file), not
a real ACL problem. This matters more here than for the earlier
plugin-asset fix (helpers/ui_server.py's _send_file_with_lock_retry):
a core prompt file failing to read can abort building the prompt for an
entire turn, not just one HTTP request.
"""

import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import files


def test_a_transient_lock_error_is_retried_and_recovers(monkeypatch):
    calls = []

    def flaky_read():
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("file is locked")
        return "the content"

    monkeypatch.setattr(time, "sleep", lambda *_: None)

    result = files._read_with_lock_retry(flaky_read)

    assert result == "the content"
    assert len(calls) == 3


def test_a_lock_error_that_never_clears_still_raises(monkeypatch):
    """Retries must be bounded - a genuine permission problem (bad ACL,
    missing file) must still surface as an error, not retry forever or
    get silently swallowed."""
    calls = []

    def always_locked():
        calls.append(1)
        raise PermissionError("permanently denied")

    monkeypatch.setattr(time, "sleep", lambda *_: None)

    with pytest.raises(PermissionError):
        files._read_with_lock_retry(always_locked, attempts=3)

    assert len(calls) == 3


def test_the_happy_path_does_not_retry_at_all():
    calls = []

    def working_read():
        calls.append(1)
        return "the content"

    result = files._read_with_lock_retry(working_read)

    assert result == "the content"
    assert len(calls) == 1


def test_a_non_lock_exception_is_not_retried():
    """Only PermissionError/OSError are transient-lock candidates - any
    other exception (e.g. a parsing error) must surface immediately."""
    calls = []

    def broken_parse():
        calls.append(1)
        raise ValueError("not valid json")

    with pytest.raises(ValueError):
        files._read_with_lock_retry(broken_parse)

    assert len(calls) == 1


def test_read_file_retries_through_a_transient_lock(tmp_path, monkeypatch):
    """Integration: a real read_file() caller benefits from the retry,
    not just the helper in isolation."""
    target = tmp_path / "some.txt"
    target.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(files, "get_abs_path", lambda p: str(target))
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    real_open = open
    calls = []

    def flaky_open(path, *a, **k):
        calls.append(1)
        if len(calls) < 2:
            raise PermissionError("file is locked")
        return real_open(path, *a, **k)

    monkeypatch.setattr(files, "open", flaky_open, raising=False)

    assert files.read_file(str(target)) == "hello"
    assert len(calls) == 2
