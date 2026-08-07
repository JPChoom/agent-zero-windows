# Safety Policy

Deterministically denies destructive/high-risk terminal commands before
`code_execution_tool` runs them, regardless of the agent's stated intent.

## How it works

`tool_execute_before` fires with the literal command text before
`code_execution_tool.execute()` does anything (before multiline grouping,
before secrets are substituted in). If the command matches one of the
built-in deny categories (or a custom pattern you've added), it's rejected
with a `RepairableException` - the tool never runs, and the agent gets a
warning explaining why instead of the command executing. Every denial is
logged to `usr/safety_policy_audit.jsonl`.

## Enabled by default

Unlike `_coding_controller`'s completion gate, this only ever intervenes on
commands no legitimate coding workflow needs - registry/persistence writes,
credential dumping, obfuscated PowerShell, destructive deletes outside the
workdir, disk/reboot operations, firewall/Defender changes, privilege
escalation, and account changes. Turn it off entirely via `enforce_policy`
in this plugin's settings if needed; add more patterns via
`custom_deny_patterns`.

## Scope and limitations - read before relying on this

**This is not a sandbox.** It's regex/substring matching on literal command
text, not a real PowerShell parser. A determined adversarial payload can
still evade it: string concatenation, variable indirection to build a
command at runtime, alternate cmdlet aliases, or splitting a dangerous
operation across multiple otherwise-innocuous commands. The existing
`usr/plugins/terminal_access` plugin's own README says the same thing about
its (smaller) denylist, and it's just as true here.

**Only the `terminal` runtime is covered.** `code_execution_tool`'s
`python` and `nodejs` runtimes can express the same dangerous intents in
Python/JS source (e.g. `subprocess.run(["reg", "add", ...])`,
`winreg.CreateKey(...)`) that these regexes are not designed to catch. This
is a real, known gap, not an oversight - policing arbitrary Python/JS
source for equivalent intent is a much larger undertaking than pattern-
matching PowerShell/cmd command lines, and out of scope for this pass.

**No approval flow.** The hand-off vision for this kind of gate includes a
three-way ALLOW / REQUIRE_APPROVAL / DENY decision. This fork has no
primitive for "pause this specific action and wait for an explicit human
approve/deny reply" (confirmed - only a coarse, global `/pause`/`/resume`
exists). So this plugin is two-way: ALLOW or DENY. Anything not on the
deny list is allowed and unaudited (only denials are logged).

**`_coding_controller`'s adapters are not affected.** They run
`dotnet build`/`npm test` via direct subprocess, not through
`code_execution_tool`, so they never pass through this gate.

## Not yet implemented

Real PowerShell AST-based analysis (the hand-off's own recommended
long-term approach - regex is explicitly called out there as insufficient);
an approval-required tier; audited/logged ALLOW decisions, not just denials;
tamper-evident/hash-chained audit log; policing the `python`/`nodejs`
runtimes; a restricted execution broker running commands under a reduced-
privilege token (this is inherently an OS-level component, not something a
Python plugin can provide - the hand-off itself suggests a separate C#/.NET
process for this).
