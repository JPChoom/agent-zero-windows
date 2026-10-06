"""PowerShell-backed queries (events, scheduled tasks, Store apps, devices...).

PowerShell is used only where Windows offers no other API. Rules:

- Scripts are **constants in this file**. No text from the model or from a
  query result is ever put into script text.
- Arguments go in as one ASCII JSON object in the `A0W_ARGS` environment
  variable and are read with `ConvertFrom-Json`: never on the command line,
  never interpolated.
- The script is the `-Command` argument of the system's own powershell.exe
  (absolute path), with -NoProfile -NonInteractive, no window, and a timeout.
  (Not stdin: PowerShell only runs a multi-line statement read from stdin
  after a blank line, which silently drops whole scripts.) Scripts use
  single-quoted strings only, so argv quoting has nothing to get wrong.
- Every script (prelude + body) must pass `check_script`: only allowlisted
  read-only cmdlets, no aliases for write verbs, no redirection, no call
  operator, no dangerous .NET statics, ASCII only. That scan is
  defense in depth for *our own constants* (a test runs it over SCRIPTS);
  it is not a sandbox for untrusted input, which never reaches a script.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from typing import Any

# Cmdlets scripts may use. Add one only after reading what it can do; the
# test that scans SCRIPTS fails on anything else.
ALLOWED_CMDLETS = frozenset({
    "Get-Service", "Get-WinEvent", "Get-ScheduledTask", "Get-ScheduledTaskInfo",
    "Get-CimInstance", "Get-AppxPackage", "Get-PnpDevice", "Get-PhysicalDisk",
    "Get-Date",
    "Select-Object", "Where-Object", "ForEach-Object", "Sort-Object",
    "Measure-Object", "Group-Object", "ConvertTo-Json", "ConvertFrom-Json",
})

_DANGEROUS_ALIASES = (
    "iex", "ni", "sc", "rm", "ri", "del", "erase", "kill", "spps", "saps", "start",
    "ii", "curl", "wget", "iwr", "irm", "copy", "cp", "move", "mv", "mi", "ren",
    "rni", "md", "mkdir", "rd", "rmdir", "cpi", "si", "sp", "sv", "clc", "clp",
    "clv", "set", "tee", "sleep", "sal", "nal", "ac", "ipmo", "icm", "ise",
)

_STRING_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"`]|`.)*\"", re.DOTALL)
_CMDLET_RE = re.compile(r"(?<![\w$.\-])([A-Za-z]+-[A-Za-z][A-Za-z0-9]*)\b")
_ALIAS_RE = re.compile(
    r"(?:^|[|;{(\n])\s*(" + "|".join(_DANGEROUS_ALIASES) + r")\b(?!\s*=)", re.IGNORECASE
)
_FORBIDDEN = [
    (re.compile(r"(?<![<\-=])>"), "redirection (>)"),
    (re.compile(r"&"), "call operator or &"),
    (re.compile(r"-enc(?:odedcommand)?\b", re.IGNORECASE), "-EncodedCommand"),
    (re.compile(r"\[\s*(?:System\.)?(?:Net|IO|Diagnostics|Reflection|Runtime|Activator|Management\.Automation)\b", re.IGNORECASE), "dangerous .NET type"),
    (re.compile(r"::\s*(?:Set|Start|Create|Delete|Kill|Load|Invoke|Exec|Open|Copy|Move|Append|Write|Remove)", re.IGNORECASE), "static method that changes state"),
    (re.compile(r"\bAdd-Type\b|\bNew-Object\b|\bImport-Module\b", re.IGNORECASE), "type/module loading"),
]


class PsError(Exception):
    pass


class NeedsAdmin(PsError):
    """Windows refused because the query needs administrator rights."""


def scan_problems(script: str) -> list[str]:
    """Reasons `script` is not an allowed read-only script (empty = fine)."""
    problems: list[str] = []
    if not script.isascii():
        problems.append("script must be ASCII")
    if '"' in script:
        problems.append("scripts may use single-quoted strings only (no double quotes)")
    bare = _STRING_RE.sub("''", script)
    for name in sorted(set(_CMDLET_RE.findall(bare))):
        if name not in ALLOWED_CMDLETS:
            problems.append(f"cmdlet not allowed: {name}")
    for match in _ALIAS_RE.finditer(bare):
        problems.append(f"alias not allowed at command position: {match.group(1)}")
    for pattern, label in _FORBIDDEN:
        if pattern.search(bare):
            problems.append(f"forbidden: {label}")
    return problems


PRELUDE = """\
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$a = $env:A0W_ARGS | ConvertFrom-Json
function emit($o) { [Console]::Out.Write((ConvertTo-Json -InputObject $o -Compress -Depth 6)) }
"""

# name -> script body. Each ends by calling emit(<array or object>).
SCRIPTS: dict[str, str] = {
    # Round-trips the arguments untouched; used by tests to prove arguments
    # stay data, and as a cheap "is PowerShell usable" probe.
    "selftest": """\
emit @{ ok = $true; echo = $a.echo; psversion = $PSVersionTable.PSVersion.ToString() }
""",
    # args: log, level, since_hours, provider?, event_id?, limit
    "events": """\
$levels = @{ critical = @(1); error = @(1,2); warning = @(1,2,3); information = @(0,1,2,3,4) }
$f = @{ LogName = $a.log; Level = $levels[$a.level]; StartTime = (Get-Date).AddHours(-[double]$a.since_hours) }
if ($a.provider) { $f.ProviderName = $a.provider }
if ($null -ne $a.event_id) { $f.Id = [int]$a.event_id }
try { $ev = @(Get-WinEvent -FilterHashtable $f -MaxEvents ([int]$a.limit) -ErrorAction Stop) }
catch { if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { $ev = @() } else { throw } }
emit @($ev | ForEach-Object { @{ t = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'); level = [string]$_.LevelDisplayName; provider = [string]$_.ProviderName; id = $_.Id; msg = ([string]$_.Message -replace '\\s+', ' ') } })
""",
    # args: name?, state, include_microsoft, logon_only, limit
    "tasks": """\
$t = @(Get-ScheduledTask -ErrorAction Stop)
if (-not $a.include_microsoft) { $t = @($t | Where-Object { $_.TaskPath -notlike '\\Microsoft\\*' }) }
if ($a.name) { $n = ([string]$a.name).ToLower(); $t = @($t | Where-Object { $_.TaskName.ToLower().Contains($n) }) }
if ($a.state -ne 'all') { $s = [string]$a.state; $t = @($t | Where-Object { [string]$_.State -eq $s }) }
if ($a.logon_only) { $t = @($t | Where-Object { @($_.Triggers | Where-Object { $_.CimClass.CimClassName -like '*Logon*' -or $_.CimClass.CimClassName -like '*Boot*' }).Count -gt 0 }) }
$total = $t.Count
$rows = @($t | Sort-Object TaskPath, TaskName | Select-Object -First ([int]$a.limit) | ForEach-Object {
  $i = $_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
  $act = @($_.Actions)[0]
  @{ name = $_.TaskName; path = $_.TaskPath; state = [string]$_.State; author = [string]$_.Author;
     next = $(if ($i -and $i.NextRunTime) { $i.NextRunTime.ToString('yyyy-MM-dd HH:mm') } else { '' });
     last = $(if ($i -and $i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $i.LastRunTime.ToString('yyyy-MM-dd HH:mm') } else { '' });
     result = $(if ($i) { '0x{0:X}' -f $i.LastTaskResult } else { '' });
     exe = $(if ($act) { ([string]$act.Execute + ' ' + [string]$act.Arguments).Trim() } else { '' }) }
})
emit @{ total = $total; rows = $rows }
""",
    # args: problems_only, device_class?, limit
    "devices": """\
$d = @(Get-PnpDevice -PresentOnly -ErrorAction Stop)
if ($a.problems_only) { $d = @($d | Where-Object { [string]$_.Status -ne 'OK' }) }
if ($a.device_class) { $c = ([string]$a.device_class).ToLower(); $d = @($d | Where-Object { ([string]$_.Class).ToLower() -eq $c }) }
$rows = @($d | Sort-Object Class, FriendlyName | Select-Object -First ([int]$a.limit) | ForEach-Object {
  @{ name = [string]$_.FriendlyName; cls = [string]$_.Class; status = [string]$_.Status; problem = [string]$_.Problem; maker = [string]$_.Manufacturer } })
emit @{ total = $d.Count; rows = $rows }
""",
    # args: name?
    "store_apps": """\
$p = @(Get-AppxPackage -ErrorAction Stop | Where-Object { -not $_.IsFramework -and [string]$_.SignatureKind -ne 'System' })
if ($a.name) { $n = ([string]$a.name).ToLower(); $p = @($p | Where-Object { $_.Name.ToLower().Contains($n) }) }
emit @($p | ForEach-Object { @{ name = [string]$_.Name; version = [string]$_.Version; publisher = (([string]$_.Publisher -replace ',.*$', '') -replace '^CN=', '') } })
""",
    "gpu": """\
emit @(Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object { @{ name = [string]$_.Name; driver = [string]$_.DriverVersion; mode = ([string]$_.CurrentHorizontalResolution + 'x' + [string]$_.CurrentVerticalResolution) } })
""",
    "disk_health": """\
emit @(Get-PhysicalDisk -ErrorAction Stop | ForEach-Object { @{ name = [string]$_.FriendlyName; media = [string]$_.MediaType; bus = [string]$_.BusType; health = [string]$_.HealthStatus; status = (@($_.OperationalStatus) -join ','); size = $_.Size } })
""",
}


def build_script(name: str) -> str:
    body = SCRIPTS[name]
    full = (
        PRELUDE
        + "try {\n"
        + body
        + "\n} catch { [Console]::Error.Write($_.Exception.Message); exit 1 }\nexit 0\n"
    )
    problems = scan_problems(full)
    if problems:
        raise PsError(f"script {name!r} is not allowed: {'; '.join(problems)}")
    return full


def powershell_path() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


_ADMIN_HINTS = ("unauthorized operation", "access is denied", "requires elevation", "administrator")


def interpret(returncode: int, stdout: str, stderr: str) -> Any:
    """Parse a finished run: JSON on success, a typed error otherwise."""
    if returncode != 0:
        message = (stderr or stdout or "PowerShell failed").strip()
        if any(h in message.lower() for h in _ADMIN_HINTS):
            raise NeedsAdmin(
                "Windows refused: this needs administrator rights, and Agent Zero runs as a standard user. "
                "Tell the user instead of retrying."
            )
        raise PsError(message.splitlines()[0][:300] if message else "PowerShell failed")
    text = (stdout or "").strip().lstrip("\ufeff")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PsError(f"PowerShell returned something that is not JSON ({exc.msg})")


_slots = threading.BoundedSemaphore(2)  # at most two PowerShell queries at once


def run_script(name: str, args: dict | None = None, timeout: float = 30) -> Any:
    script = build_script(name)
    payload = json.dumps(args or {}, ensure_ascii=True)  # ASCII: \\uXXXX escapes survive any code page
    env = {**os.environ, "A0W_ARGS": payload, "POWERSHELL_TELEMETRY_OPTOUT": "1"}
    with _slots:
        try:
            proc = subprocess.run(
                [powershell_path(), "-NoProfile", "-NonInteractive", "-Command", script],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise PsError(f"the query took longer than {timeout:g}s and was stopped; narrow it with filters")
        except FileNotFoundError:
            raise PsError("powershell.exe was not found")
    return interpret(proc.returncode, proc.stdout, proc.stderr)
