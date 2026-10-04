"""The Bypass-mode password: separate from the web UI login, stored only as
a salted PBKDF2-SHA256 hash in `usr/permissions_bypass.json`.

No password set = Bypass cannot be unlocked at all (the selector tells the
user to set one in Settings > Security). Failed attempts go through the same
lockout as the login form, keyed by client, and are audited.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading

from helpers import files

HASH_FILE = "usr/permissions_bypass.json"
ITERATIONS = 600_000
MIN_LENGTH = 8

_lock = threading.Lock()


class BypassPasswordError(ValueError):
    pass


def _path() -> str:
    return files.get_abs_path(HASH_FILE)


def _load() -> dict | None:
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("hash") and data.get("salt"):
            return data
    except (OSError, ValueError):
        pass
    return None


def _derive(password: str, salt_hex: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations
    ).hex()


def is_set() -> bool:
    return _load() is not None


def verify(password: str | None) -> bool:
    data = _load()
    if not data or not password:
        return False
    candidate = _derive(password, data["salt"], int(data.get("iterations", ITERATIONS)))
    return hmac.compare_digest(candidate, data["hash"])


def set_password(new_password: str, current_password: str | None = None) -> None:
    """Set or change the password. Changing requires the current one."""
    new_password = new_password or ""
    if len(new_password) < MIN_LENGTH:
        raise BypassPasswordError(f"Bypass password must be at least {MIN_LENGTH} characters.")
    try:
        from helpers import dotenv

        if new_password == (dotenv.get_dotenv_value(dotenv.KEY_AUTH_PASSWORD) or None):
            raise BypassPasswordError("Use a different password from the web UI login.")
    except BypassPasswordError:
        raise
    except Exception:
        pass

    with _lock:
        if is_set() and not verify(current_password):
            raise BypassPasswordError("Current Bypass password is incorrect.")
        salt = secrets.token_hex(16)
        record = {
            "algorithm": "pbkdf2_sha256",
            "iterations": ITERATIONS,
            "salt": salt,
            "hash": _derive(new_password, salt, ITERATIONS),
        }
        path = _path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        os.replace(tmp, path)
