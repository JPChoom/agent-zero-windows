### coding_gate
run lint/build/test quality gates (dotnet build, npm test, PSScriptAnalyzer) for a detected project and report pass/fail with diagnostics
args: `action` `check` (default) or `status`; optional `path` (file/folder in the project; omit to check every project changed since the last check)
- if the project's automatic completion gate is on, it runs by itself and blocks a false "done"; call this mid-task or when the gate is off
- SKIPPED = tool not found or no supported project at that path - neither pass nor fail
- fix the smallest cause of a FAILED diagnostic; never disable tests, suppress warnings, or weaken build settings to pass
~~~json
{"thoughts": ["Verify the build before responding."], "headline": "Running coding gate", "tool_name": "coding_gate", "tool_args": {"action": "check"}}
~~~
