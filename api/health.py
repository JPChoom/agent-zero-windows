from helpers.api import ApiHandler, Request, Response
from helpers import errors, git
from helpers.access_control import is_local_request

class HealthCheck(ApiHandler):

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        # Unauthenticated by design (startup probe, launcher, self-update
        # poller all hit it). Version details only go to callers on this
        # machine; anything remote/proxied just learns it's up.
        if not is_local_request(request.remote_addr, request.headers):
            return {"ok": True}

        gitinfo = None
        error = None
        try:
            gitinfo = git.get_git_info()
        except Exception as e:
            error = errors.error_text(e)

        return {"ok": True, "gitinfo": gitinfo, "error": error}
