### coding_gate
run lint/build/test quality gates for a detected project (.NET dotnet build, npm test, PowerShell PSScriptAnalyzer lint) and report pass/fail with diagnostics
args:
- `action`: `check` (default) or `status`
- `path`: optional; a file or folder inside the project to check. Omit to check every project with tracked changes since the last check.
rules:
- when the automatic completion gate is enabled for a project (see the plugin's settings), you do not need to call this manually before finishing - it runs automatically and blocks a false "done" response until it passes
- use this to check progress mid-task, or when the automatic gate is disabled for the current project
- a "SKIPPED" result means the required tool (dotnet/npm/PowerShell) was not found or no supported project was detected at that path - it is not a pass or a fail
- fix the smallest cause of a FAILED diagnostic; do not disable tests, suppress warnings, or weaken build settings just to make the gate pass
examples:
1 check all tracked changes
~~~json
{
    "thoughts": [
        "I finished editing the project files.",
        "Let me verify the build actually passes before responding.",
    ],
    "headline": "Running coding gate check",
    "tool_name": "coding_gate",
    "tool_args": {
        "action": "check"
    }
}
~~~

2 check a specific project explicitly
~~~json
{
    "thoughts": [
        "The automatic gate is off for this project, so I'll check it manually.",
    ],
    "headline": "Checking build for C:\\Projects\\MyApp",
    "tool_name": "coding_gate",
    "tool_args": {
        "action": "check",
        "path": "C:\\Projects\\MyApp"
    }
}
~~~
