# Coding Controller

Runs lint/build/test quality gates after code edits and blocks a false
"done" response until they pass, with a bounded automatic repair loop.

## How it works

1. When `_text_editor` writes or patches a file, this plugin detects the
   containing project (`.sln`/`.csproj`/`.fsproj`/`.vbproj` -> dotnet,
   `package.json` -> npm, a standalone `.ps1` -> PowerShell lint) and marks
   it dirty.
2. When the agent tries to finish its turn (the `response` tool), any dirty
   project is gated: the relevant commands run directly via subprocess
   (not the interactive terminal), and diagnostics are parsed where the
   output format is stable enough to (currently: dotnet/MSBuild).
3. On failure, only *new* problems block the turn - see "Baseline
   tracking" below. When there is a new failure, the turn is not allowed
   to end: the agent gets a bounded number of automatic repair attempts
   (`max_repair_attempts`, default 3) with the new failure's diagnostics
   fed back to it, before the response is allowed through with an
   explicit "still failing" note instead of a false success claim.

## Baseline tracking

The gate only blocks on failures introduced during the task, not ones a
project already had. The first time a project is seen failing, that
failure set becomes its baseline (not blocked - you get a note instead)
rather than trapping the agent trying to fix pre-existing problems it
wasn't asked to fix. Only a failure beyond that baseline (a real
regression) blocks completion. Diagnostics are matched by
`(file, error_code, message)`, not line number, so an earlier edit
shifting line numbers doesn't make an old, unrelated diagnostic look new.

Caveat: the baseline is necessarily captured *after* the agent's first
edit to a project in a session (there's no pre-task snapshot step), so a
regression introduced on that very first edit can slip into the baseline
undetected. A future pass wiring this into `_time_travel`'s snapshot API
could capture a true pre-edit baseline instead.

## Off by default

`enforce_completion_gate` defaults to `false`. The gate stays silent for
every project until you turn it on (per project/agent, via this plugin's
settings screen) for one you've verified the configured commands work for.
The manual `coding_gate` tool works regardless of this setting, for
on-demand checks.

## Adapters (v1)

- **dotnet**: `dotnet restore` (optional) + `dotnet build`, with structured
  MSBuild diagnostic parsing (`file(line,col): error/warning CODE: message`).
- **npm**: `npm install` (optional) + `npm test`, raw output tail only (test
  runner output formats vary too much to parse generically).
- **PowerShell**: `Invoke-ScriptAnalyzer` lint if PSScriptAnalyzer is
  installed; skipped gracefully otherwise.

Not yet implemented: Python, Go, Rust, Java adapters (same shape as
dotnet/npm, straightforward to add); worsening-state rollback via
`_time_travel`'s snapshot/`travel()` API (storage layer already exists in
this fork, just not wired in here yet); an independent read-only review
step; fast/full gate split.

## Scope limits

This restricts *what runs and when* (gate commands, on a bounded schedule).
It is not a sandbox and does not restrict *what those commands can do* -
`dotnet build`/`npm test` can execute arbitrary project-defined build
scripts. Only enable the completion gate for projects you trust.
