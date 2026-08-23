from helpers.api import ApiHandler, Input, Output, Request, Response
from helpers.plugin_review import run_scoped_review
from plugins._plugin_validator.helpers.prompt import build_prompt


class PluginValidatorRun(ApiHandler):
    """
    POST /api/plugins/_plugin_validator/plugin_validator_run
    Body:    { "source": "local|git", "target": "<plugin name or git url>", "checks": [...] }
    Returns: { "ok": true, "source": "local|git", "target": "...", "report": "<markdown>" }

    Combines plugin_validator_queue + plugin_validator_start into one synchronous call and awaits the result.
    No server-side timeout - set an appropriate client-side timeout for large repositories.
    """

    async def process(self, input: Input, request: Request) -> Output:
        source: str = input.get("source", "local").strip().lower()
        target: str = input.get("target", "").strip()

        if source not in {"local", "git"}:
            return Response("Unsupported 'source'. Use 'local' or 'git'.", 400)
        if not target:
            return Response("Missing 'target'.", 400)

        try:
            prompt = build_prompt(source, target, input.get("checks"))
            report = await run_scoped_review(self, prompt)
        except Exception as e:
            return Response(f"Validation failed: {e}", 500)

        return {
            "ok": True,
            "source": source,
            "target": target,
            "report": report,
        }
