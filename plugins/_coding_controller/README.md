# Coding Controller

Runs lint/build/test quality gates after code edits and blocks a false
"done" response until they pass, with a bounded, checkpointed automatic
repair loop, independent read-only review, and root-cause diagnosis on
give-up.

## How it works

1. When `_text_editor` writes or patches a file, this plugin detects the
   containing project (see "Adapters" below for the full marker list) and
   marks it dirty.
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
4. Before each repair attempt, the current file state is checkpointed. If
   the next attempt makes things strictly worse (more failures, or a
   previously-passing stage now failing), it's automatically rolled back
   to that checkpoint rather than left as the foundation for the next
   attempt - see `helpers/checkpoint.py`.
5. Once a project's gate passes cleanly, an independent, read-only
   "coding-reviewer" sub-agent can optionally inspect the diff before the
   response is allowed through (`enable_independent_review`, off by
   default - see `helpers/reviewer.py`).
6. If the repair loop exhausts its attempt budget without clearing a new
   failure, a "coding-diagnostician" sub-agent can optionally explain the
   likely root cause as an advisory note (`enable_diagnostician`, off by
   default - see `helpers/diagnostician.py`). Purely informational; never
   re-blocks completion.

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

## Adapters

- **dotnet** (`.sln`/`.csproj`/`.fsproj`/`.vbproj`): `dotnet restore`
  (optional) + `dotnet build`, with structured MSBuild diagnostic parsing
  (`file(line,col): error/warning CODE: message`).
- **npm** (`package.json`): `npm install` (optional) + `npm test`, raw
  output tail only (test runner output formats vary too much to parse
  generically).
- **PowerShell** (standalone `.ps1`): `Invoke-ScriptAnalyzer` lint if
  PSScriptAnalyzer is installed; skipped gracefully otherwise.
- **Python** (`pyproject.toml`/`setup.py`/`requirements.txt`): `ruff check`
  + `ruff format --check` (if ruff installed) and `pytest` (if installed) -
  judged per-tool, only skips entirely if neither is found.
- **Go** (`go.mod`): `gofmt -l` (if found) + `go vet` + `go build` +
  `go test`.
- **Rust** (`Cargo.toml`): `cargo fmt --check` + `cargo clippy` +
  `cargo build` + `cargo test` - all four run regardless of earlier
  failures.
- **Java/Kotlin** (`pom.xml` or `build.gradle`/`build.gradle.kts`): one
  test-target run via Maven or Gradle (whichever marker matched),
  preferring the project's own `mvnw`/`gradlew` wrapper - "moderate"
  support, no dedicated Checkstyle/ktlint invocation.
- **C/C++** (`CMakeLists.txt`): CMake configure + build (out-of-source,
  into `build/`), `ctest` if configured, `clang-format`/`clang-tidy` only
  if found on PATH.

Explicitly out of scope: Unity/Unreal/Godot adapters.

## Per-project configuration

Every field below is already overridable per Agent Zero "project" through
this plugin's own Settings screen (the "Project" selector there scopes
the stored config file, same mechanism every other plugin uses - no
extra code needed for that).

For build-command config you'd rather commit to the repo itself and
share via version control instead of configuring per-user in Settings,
drop a `coding.yaml` file in the project's own root directory. It's
layered on top of the Settings-UI config and wins for the keys it sets:
`command_timeout_seconds`, `dotnet_restore_first`, `dotnet_build_args`,
`npm_install_first`, `npm_test_args`, `powershell_lint_enabled`,
`python_test_args`, `go_test_args`, `rust_build_args`,
`java_maven_test_args`, `java_gradle_test_args`. The enforcement toggles
(`enforce_completion_gate`, `max_repair_attempts`,
`enable_independent_review`, `enable_diagnostician`,
`review_blocking_severity`) are deliberately **not** overridable from
`coding.yaml` - they're evaluated once, before any project root is even
known, so a repo-local file silently flipping them would be a confusing
surprise. Those stay Settings-UI-only. A missing or malformed
`coding.yaml` is ignored, not an error.

## Scope limits

This restricts *what runs and when* (gate commands, on a bounded schedule).
It is not a sandbox and does not restrict *what those commands can do* -
`dotnet build`/`npm test` can execute arbitrary project-defined build
scripts. Only enable the completion gate for projects you trust.
