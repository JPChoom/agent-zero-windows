from helpers.tool import Tool, Response
from plugins._coding_controller.helpers import gate_controller, session_state
from plugins._coding_controller.helpers.config import get_config


class CodingGate(Tool):

    async def execute(self, **kwargs) -> Response:
        action = str(self.args.get("action") or "check").strip().lower()
        cfg = get_config(self.agent)

        if action == "status":
            return await self._status(cfg)
        return await self._check(cfg)

    async def _check(self, cfg: dict) -> Response:
        path = str(self.args.get("path") or "").strip()

        if not path:
            dirty = session_state.get_dirty_roots(self.agent)
            if not dirty:
                return Response(
                    message="No tracked code changes to check. Pass `path` to check a specific project explicitly.",
                    break_loop=False,
                )
            summaries = []
            for root, kind in dirty.items():
                result = await gate_controller.run_gate_for_root(root, kind, cfg)
                summaries.append(_format_result(root, result))
                if result.get("passed") or result.get("skipped"):
                    session_state.clear_dirty(self.agent, root)
            return Response(message="\n\n".join(summaries), break_loop=False)

        result = await gate_controller.run_gate_for_path(path, cfg)
        return Response(message=_format_result(result.get("root") or path, result), break_loop=False)

    async def _status(self, cfg: dict) -> Response:
        dirty = session_state.get_dirty_roots(self.agent)
        gate_state = "ON" if cfg["enforce_completion_gate"] else "OFF"
        if not dirty:
            return Response(message=f"Completion gate: {gate_state}\nNo projects currently marked dirty.", break_loop=False)
        lines = [
            f"- {root} ({kind}), repair attempts: {session_state.get_repair_attempts(self.agent, root)}"
            for root, kind in dirty.items()
        ]
        return Response(
            message=f"Completion gate: {gate_state}\nDirty projects:\n" + "\n".join(lines),
            break_loop=False,
        )


def _format_result(root: str, result: dict) -> str:
    if result.get("skipped"):
        return f"{root}: SKIPPED - {result.get('reason')}"
    status = "PASSED" if result.get("passed") else "FAILED"
    lines = [f"{root}: {status}"]
    for stage in result.get("stages", []):
        lines.append(
            f"  - {stage['name']}: {'ok' if stage['passed'] else 'FAILED'} "
            f"(exit {stage['exit_code']}, {stage['duration_ms']}ms)"
        )
        for diag in (stage.get("diagnostics") or [])[:10]:
            lines.append(
                f"    {diag['severity']} {diag['code']} {diag['file']}({diag['line']},{diag['column']}): {diag['message']}"
            )
    return "\n".join(lines)
