from helpers.api import ApiHandler, Request, Response
from helpers.file_browser import list_directory_absolute
from helpers import runtime


class GetFolderBrowserFiles(ApiHandler):
    """Lists a directory's subfolders by absolute path, with no workdir
    containment check - backs the folder picker used when configuring
    tiered filesystem access in Settings.

    This is deliberately distinct from GetWorkDirFiles: that endpoint is
    what the agent-facing file browser uses and is hard-restricted to the
    configured workdir. This one exists only for the user, already on an
    authenticated Settings page, to pick a folder anywhere on their own
    machine - not a new capability the agent gains any access through.
    """

    @classmethod
    def get_methods(cls):
        return ["GET"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        path = request.args.get("path", "")
        result = await runtime.call_development_function(list_directory_absolute, path)
        return {"data": result}
