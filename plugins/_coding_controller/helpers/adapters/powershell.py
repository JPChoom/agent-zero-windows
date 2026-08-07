"""PowerShell lint adapter: PSScriptAnalyzer if installed, otherwise skipped
gracefully (this is defense-in-depth quality checking, not a hard
requirement - a missing analyzer shouldn't block completion by itself).
"""

from plugins._coding_controller.helpers.find_binary import find_executable
from plugins._coding_controller.helpers.process_runner import run_command


def find_powershell() -> str:
    return find_executable(("pwsh", "powershell"))


async def run_gate(project_root: str, cfg: dict) -> dict:
    if not cfg.get("powershell_lint_enabled", True):
        return _skipped("PowerShell lint disabled in plugin config")

    pwsh = find_powershell()
    if not pwsh:
        return _skipped("no PowerShell executable (pwsh/powershell) found")

    script = (
        "if (-not (Get-Module -ListAvailable -Name PSScriptAnalyzer)) { "
        "Write-Output 'PSScriptAnalyzer not installed'; exit 0 }; "
        f"$results = Invoke-ScriptAnalyzer -Path '{project_root}' -Severity Error,Warning; "
        "if ($results) { $results | Format-Table -AutoSize | Out-String | Write-Output; exit 1 } "
        "else { exit 0 }"
    )
    result = await run_command(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=project_root,
        timeout_seconds=cfg.get("command_timeout_seconds", 300),
    )
    stage = {
        "name": "psscriptanalyzer",
        "command": "Invoke-ScriptAnalyzer",
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "passed": result.passed,
        "duration_ms": result.duration_ms,
        "diagnostics": [],
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
    return {"passed": stage["passed"], "skipped": False, "reason": "", "stages": [stage]}


def _skipped(reason: str) -> dict:
    return {"passed": True, "skipped": True, "reason": reason, "stages": []}
