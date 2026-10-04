from helpers.api import ApiHandler, Request, Response

from helpers import runtime

class RFC(ApiHandler):

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    async def process(self, input: dict, request: Request) -> dict | Response:
        # RFC is the bridge from a development host to its Docker twin.
        # Native Windows has no twin (runtime.call_development_function runs
        # everything locally there), so the endpoint is pure attack surface.
        if runtime.is_windows():
            return Response("Not Found", 404)
        result = await runtime.handle_rfc(input) # type: ignore
        return result
