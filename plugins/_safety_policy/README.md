# Safety Policy

Deterministically denies or holds-for-approval destructive/high-risk
terminal commands before `code_execution_tool` runs them, regardless of
the agent's stated intent.

## How it works

`tool_execute_before` fires with the literal command text before
`code_execution_tool.execute()` does anything (before multiline grouping,
before secrets are substituted in). If the command matches one of the
built-in deny categories (or a custom pattern you've added), the outcome
depends on that category's configured tier:

- **Deny** (the default for most categories): rejected immediately with a
  `RepairableException` - the tool never runs, the agent gets a warning
  explaining why instead of the command executing.
- **Require approval** (the default for `firewall_and_defender`,
  `privilege_escalation`, `account_changes`): the tool call is held, a chat
  message appears with Approve/Deny buttons, and the command only runs if
  you click Approve within `approval_timeout_seconds` (default 300s) - an
  unanswered request, a Deny click, or the timeout all deny the command the
  same way a hard deny would. `custom_deny_patterns` always hard-deny; the
  approval tier only applies to the built-in categories.

Every denial, pending approval, and resolved approval/deny is logged to
`usr/safety_policy_audit.jsonl`.

## Enabled by default

Unlike `_coding_controller`'s completion gate, this only ever intervenes on
commands no legitimate coding workflow needs - registry/persistence writes,
credential dumping, obfuscated PowerShell, destructive deletes outside the
workdir, disk/reboot operations, firewall/Defender changes, privilege
escalation, and account changes. Turn it off entirely via `enforce_policy`
in this plugin's settings if needed; add more patterns via
`custom_deny_patterns`; adjust which categories deny vs. require approval,
and the approval timeout, via this plugin's settings.

## Scope and limitations - read before relying on this

**This is not a sandbox.** It's regex/substring matching on literal command
text, not a real PowerShell parser. A determined adversarial payload can
still evade it: string concatenation, variable indirection to build a
command at runtime, alternate cmdlet aliases, or splitting a dangerous
operation across multiple otherwise-innocuous commands. The existing
`usr/plugins/terminal_access` plugin's own README says the same thing about
its (smaller) denylist, and it's just as true here.

**`python`/`nodejs` coverage is narrower than `terminal`'s.** These
runtimes are scanned only for the same dangerous command lines reached
through a shell-out call - `os.system(...)`, `subprocess.run/call/
check_call/check_output/Popen(...)`, `child_process.exec/execSync/spawn/
spawnSync/execFile/execFileSync(...)` (qualified or bare, e.g. after
`const { execSync } = require('child_process')`), in both string form
(`os.system("reg add ...")`) and list/args form (`subprocess.run(["reg",
"add", ...])`, `spawn("reg", ["add", ...])`). Matching is deliberately
scoped to text passed to those calls, not the whole file: several deny
patterns are ordinary English/programming words (`format`, `credential`)
that would false-positive constantly if scanned against arbitrary source
(`str.format()`, a `credentials` variable, ...). What this does **not**
catch: native APIs with no shell-out at all (`winreg.CreateKey(...)`,
`fs.rmSync(...)`, `ctypes.windll...`), and any indirection - building the
command from variables/concatenation, wrapping the shell-out call in a
helper function, base64-decoding it first. Policing arbitrary Python/JS
for equivalent intent in full generality is a much larger undertaking than
pattern-matching command lines, and out of scope for this pass.

**The approval flow is a same-process wait, not a durable job queue.** A
pending approval is an in-memory `asyncio.Future`
(`helpers/approval_registry.py`) - it does not survive an app restart.
Timeout, deny, and an unanswered request are all indistinguishable to the
agent (all raise the same kind of `RepairableException`); only the audit
log and the chat UI distinguish which one actually happened.

**`_coding_controller`'s adapters are not affected.** They run
`dotnet build`/`npm test` via direct subprocess, not through
`code_execution_tool`, so they never pass through this gate.

**Anything not on the deny/approval list is allowed and unaudited** - only
denials, pending approvals, and resolved approval/deny decisions are
logged, not routine allowed commands.

## Not yet implemented

Real PowerShell/Python/JS AST-based analysis (the hand-off's own
recommended long-term approach - regex is explicitly called out there as
insufficient); audited/logged ALLOW decisions, not just denials/approvals;
tamper-evident/hash-chained audit log; catching native-API
persistence/destruction in `python`/`nodejs` that never shells out
(`winreg`, `fs.rmSync`, `ctypes`, ...); a restricted execution broker
running commands under a reduced-privilege token (this is inherently an
OS-level component, not something a Python plugin can provide - the
hand-off itself suggests a separate C#/.NET process for this).
