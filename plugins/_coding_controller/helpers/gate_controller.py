"""Orchestrates project detection -> adapter selection -> gate execution ->
structured result, for both the automatic completion gate and the manual
coding_gate tool.
"""

from plugins._coding_controller.helpers import project_detector
from plugins._coding_controller.helpers.adapters import dotnet, npm, powershell

_ADAPTERS = {
    "dotnet": dotnet.run_gate,
    "npm": npm.run_gate,
    "powershell": powershell.run_gate,
}


async def run_gate_for_root(root: str, kind: str, cfg: dict) -> dict:
    """Run the gate for an already-known project root/kind (no re-detection)."""
    runner = _ADAPTERS.get(kind)
    if runner is None:
        return {
            "passed": True, "skipped": True,
            "reason": f"no adapter for project kind '{kind}'",
            "kind": kind, "root": root, "stages": [],
        }
    result = await runner(root, cfg)
    result["kind"] = kind
    result["root"] = root
    return result


async def run_gate_for_path(path: str, cfg: dict) -> dict:
    """Detect the project at/above `path` and run its gate."""
    info = project_detector.detect_project(path)
    if info is None:
        return {
            "passed": True, "skipped": True,
            "reason": "no supported project (.sln/.csproj/package.json/.ps1) found",
            "kind": "", "root": "", "stages": [],
        }
    return await run_gate_for_root(info.root, info.kind, cfg)
