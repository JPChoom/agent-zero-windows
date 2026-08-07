"""Structured diagnostic parsing for gate command output.

v1 covers dotnet/MSBuild's stable diagnostic line format. Other adapters
(npm, PowerShell) fall back to a raw stdout/stderr tail - their output
formats vary too much (Jest vs. mocha vs. tap, etc.) to parse reliably
without picking a specific test runner to special-case.
"""

import re

_DOTNET_DIAG_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\):\s+"
    r"(?P<severity>error|warning)\s+(?P<code>[A-Za-z]+\d+)\s*:\s*"
    r"(?P<message>.+?)\s*(?:\[.*\])?$"
)


def parse_dotnet_diagnostics(output: str) -> list[dict]:
    diagnostics = []
    for line in output.splitlines():
        match = _DOTNET_DIAG_RE.match(line.strip())
        if not match:
            continue
        diagnostics.append(
            {
                "file": match.group("file"),
                "line": int(match.group("line")),
                "column": int(match.group("col")),
                "severity": match.group("severity"),
                "code": match.group("code"),
                "message": match.group("message").strip(),
            }
        )
    return diagnostics


# ------------------------------------------------------------------
# Baseline fingerprinting
#
# Used to tell "this project already had this problem before the agent
# touched it" apart from "the agent's edit introduced this." Line/column
# numbers are deliberately excluded from the fingerprint: an earlier edit
# in the same file can shift every line below it, which would otherwise
# make an unrelated pre-existing diagnostic look "new" on every check.
# ------------------------------------------------------------------

def fingerprint_stage(stage: dict) -> frozenset:
    """Return a stable, comparable signature for a failed stage's problems.

    With structured diagnostics (currently: dotnet), the fingerprint is the
    set of (file, code, message) tuples for error-severity diagnostics.
    Without them (npm, PowerShell), there's nothing finer-grained to key
    on, so the whole stage collapses to a single sentinel meaning "this
    stage was failing" - still enough to distinguish "still the same
    failure as before" from "this used to pass and now doesn't."
    """
    if stage.get("passed"):
        return frozenset()

    diagnostics = [d for d in (stage.get("diagnostics") or []) if d.get("severity") == "error"]
    if diagnostics:
        return frozenset((d["file"], d["code"], d["message"]) for d in diagnostics)

    return frozenset({("__stage_failed__", stage.get("name", ""), "")})
