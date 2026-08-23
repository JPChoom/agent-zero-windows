from helpers.api import ApiHandler, Input, Output, Request, Response
from helpers.plugin_review import run_scoped_review
from plugins._plugin_scan.helpers.prompt import build_prompt


class PluginScanRun(ApiHandler):
    """
    POST /api/plugins/_plugin_scan/plugin_scan_run
    Body:    { "git_url": "https://github.com/...", "checks": [...] }  # checks optional, defaults to all
    Returns: { "ok": true, "verdict": "safe|caution|dangerous|unknown", "report": "<markdown>" }

    Combines plugin_scan_queue + plugin_scan_start into one synchronous call and awaits the result.
    No server-side timeout - set an appropriate client-side timeout (repos can take 5+ min to scan).
    """

    async def process(self, input: Input, request: Request) -> Output:
        git_url: str = input.get("git_url", "").strip()
        if not git_url:
            return Response("Missing 'git_url'.", 400)

        try:
            prompt = build_prompt(git_url, input.get("checks"))
            report = await run_scoped_review(self, prompt)
        except Exception as e:
            return Response(f"Scan failed: {e}", 500)

        return {
            "ok": True,
            "git_url": git_url,
            "report": report,
        }
