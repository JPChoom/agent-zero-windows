"""_send_file_with_lock_retry absorbs a transient Windows file-lock error
on plugin asset serving instead of surfacing a 500 for something that
would have succeeded on the very next request anyway.

Observed live: a fresh server start hit a real PermissionError serving
plugins/_discovery/webui/assets/thumb-email.png on the very first
request after startup - a well-known Windows quirk where Defender's
real-time scanner or the search indexer briefly holds a just-touched
file open. Re-requesting the same asset immediately after (no code
changes) succeeded, and a direct Flask send_file() call on the same path
worked too, confirming this is a transient OS-level lock, not a real ACL
or code issue.
"""

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import ui_server


@pytest.mark.asyncio
async def test_a_transient_lock_error_is_retried_and_recovers(monkeypatch):
    calls = []

    def flaky_send_file(path):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("file is locked")
        return f"SENT:{path}"

    real_sleep = asyncio.sleep
    monkeypatch.setattr(ui_server, "send_file", flaky_send_file)
    monkeypatch.setattr(ui_server.asyncio, "sleep", lambda _: real_sleep(0))

    result = await ui_server._send_file_with_lock_retry("C:\\some\\asset.png")

    assert result == "SENT:C:\\some\\asset.png"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_a_lock_error_that_never_clears_still_raises(monkeypatch):
    """Retries must be bounded - a genuine permission problem (bad ACL,
    missing file) must still surface as an error, not retry forever or
    get silently swallowed."""
    calls = []

    def always_locked(path):
        calls.append(1)
        raise PermissionError("permanently denied")

    real_sleep = asyncio.sleep
    monkeypatch.setattr(ui_server, "send_file", always_locked)
    monkeypatch.setattr(ui_server.asyncio, "sleep", lambda _: real_sleep(0))

    with pytest.raises(PermissionError):
        await ui_server._send_file_with_lock_retry("C:\\some\\asset.png", attempts=3)

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_the_happy_path_does_not_retry_at_all(monkeypatch):
    calls = []

    def working_send_file(path):
        calls.append(1)
        return f"SENT:{path}"

    monkeypatch.setattr(ui_server, "send_file", working_send_file)

    result = await ui_server._send_file_with_lock_retry("C:\\some\\asset.png")

    assert result == "SENT:C:\\some\\asset.png"
    assert len(calls) == 1
