from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable


APT_LOCK_TIMEOUT_SECONDS = 240
APT_LOCK_RETRY_SECONDS = 5

_apt_lock = threading.RLock()


def run_apt_with_retries(
    runner: Callable[[], subprocess.CompletedProcess[str]],
    *,
    lock_timeout_seconds: int = APT_LOCK_TIMEOUT_SECONDS,
    retry_seconds: int = APT_LOCK_RETRY_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run an apt/dpkg command, serializing in-process callers and waiting out apt locks."""

    with _apt_lock:
        deadline = time.monotonic() + max(0, lock_timeout_seconds)
        while True:
            result = runner()
            if result.returncode == 0 or not is_apt_lock_error(result):
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return result
            time.sleep(min(max(1, retry_seconds), remaining))


def is_apt_lock_error(result: subprocess.CompletedProcess[str]) -> bool:
    output = f"{result.stderr or ''}\n{result.stdout or ''}".lower()
    return (
        "could not get lock" in output
        or "unable to lock directory" in output
        or "unable to acquire the dpkg frontend lock" in output
        or "is another process using it" in output
    )
