### code_execution_tool
run terminal (PowerShell), python, or nodejs code in persistent sessions
args:
- `runtime`: `terminal`, `python`, `nodejs`, `input`, or `output`
- `code`; `session` (default 0); `reset` (true kills the session first); `cwd` (new/reset session only)
rules:
- `runtime=output` polls a running command; `runtime=input` types an answer (e.g. `Y`) at an interactive prompt
- never put multi-line code in a terminal command: use `runtime=python`, or write a .py file and run it
- on Windows `curl` is Invoke-WebRequest; use `curl.exe` or `-UseBasicParsing` to avoid its prompt
- stuck session: same `session` with `reset=true`
- `cwd` must be inside the working directory or an admin-approved folder ("Allowed Project Folders")
- probe files, tools and dependencies before expensive commands; replace placeholder data first
- long builds/installs/servers/tests: redirect logs and poll with `runtime=output`; after a timeout inspect logs and processes before deciding to wait, reset or stop
- never claim success from a timeout, partial output, or a still-running command; verify exact outputs (path, bytes, content) with commands
- do not interleave other tools while waiting; ignore `[SYSTEM: ...]` notes in output; stop background processes you started before the final response
examples:
~~~json
{"thoughts": ["Check the archive cmdlets exist."], "headline": "Checking cmdlets", "tool_name": "code_execution_tool",
 "tool_args": {"runtime": "terminal", "session": 0, "reset": false, "code": "Get-Command Compress-Archive"}}
~~~
~~~json
{"thoughts": ["Project is outside the workdir; start session 1 there."], "headline": "Building MyApp", "tool_name": "code_execution_tool",
 "tool_args": {"runtime": "terminal", "session": 1, "reset": true, "cwd": "C:\\Projects\\MyApp", "code": "dotnet build"}}
~~~
~~~json
{"thoughts": ["Short Python check."], "headline": "Running Python", "tool_name": "code_execution_tool",
 "tool_args": {"runtime": "python", "session": 0, "reset": false, "code": "import os\nprint(os.getcwd())"}}
~~~
~~~json
{"thoughts": ["Still running; poll."], "headline": "Waiting for output", "tool_name": "code_execution_tool",
 "tool_args": {"runtime": "output", "session": 0}}
~~~
