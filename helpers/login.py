from helpers import dotenv
import hashlib
import hmac
import secrets

# Per-process key for the session credential token. The session cookie is
# signed but not encrypted, so whatever is stored in it is readable by its
# holder; this used to be plain sha256(user:password), which a stolen cookie
# could be brute-forced offline against. An HMAC under a key that never
# leaves the process reveals nothing useful. Sessions already end on restart
# (the Flask secret key is per-process too), so a per-process key costs
# nothing extra.
_SESSION_KEY = secrets.token_bytes(32)


def get_credentials_hash():
    user = dotenv.get_dotenv_value(dotenv.KEY_AUTH_LOGIN)
    password = dotenv.get_dotenv_value(dotenv.KEY_AUTH_PASSWORD)
    if not user:
        return None
    return hmac.new(_SESSION_KEY, f"{user}:{password}".encode(), hashlib.sha256).hexdigest()


def is_login_required():
    user = dotenv.get_dotenv_value(dotenv.KEY_AUTH_LOGIN)
    return bool(user)
