"""Windows Intelligence foundation: argument validation, output formatting and
secret redaction, and the PowerShell runner (script scan, argument safety)."""

from __future__ import annotations

import sys

import pytest

from plugins._windows_intel.helpers import config as wcfg
from plugins._windows_intel.helpers import fmt, schema, sources_ps, validate

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")


# -- validation -------------------------------------------------------------------

def test_every_action_validates_with_no_arguments_unless_it_needs_some():
    for name, action in schema.ACTIONS.items():
        needs = [k for k, a in action.args.items() if a.required]
        if needs:
            with pytest.raises(ValueError, match="needs"):
                validate.validate(name, {})
        else:
            assert validate.validate(name, {})[0] == name


def test_defaults_and_coercion():
    action, clean = validate.validate("processes", {"limit": "25", "cmdline": "yes", "user": "ALL"}, default_limit=40)
    assert clean == {"user": "all", "sort": "memory", "cmdline": True, "limit": 25}
    _, clean = validate.validate("services", {}, default_limit=40)
    assert clean["limit"] == 40 and clean["status"] == "all"
    assert validate.normalize_action("Registry ") == "registry"
    assert validate.validate("Events", {})[1]["since"] == 24.0


def test_limits_are_capped_by_configuration():
    with pytest.raises(ValueError, match="between 1 and 100"):
        validate.validate("events", {"limit": 101})
    with pytest.raises(ValueError, match="between 1 and 200"):
        validate.validate("processes", {"limit": 300}, max_limit=200)
    with pytest.raises(ValueError):
        validate.validate("processes", {"limit": 0})
    with pytest.raises(ValueError):
        validate.validate("processes", {"limit": True})


def test_unknown_actions_and_arguments_are_rejected_helpfully():
    with pytest.raises(ValueError, match="unknown action"):
        validate.validate("format_disk", {})
    with pytest.raises(ValueError, match="does not take 'script'.*allowed arguments: name, pid"):
        validate.validate("processes", {"script": "Remove-Item C:\\"})
    with pytest.raises(ValueError, match="no arguments|allowed arguments: none"):
        validate.validate("network", {"x": 1})


@pytest.mark.parametrize("payload", [
    '"; Remove-Item -Recurse C:\\x; "',
    "'; Stop-Process -Name explorer; '",
    "$(whoami)", "`whoami`", "a\nb", "a\x00b", "a|b", "a;b", "a&b", "a>b", "a<b",
    "${env:USERNAME}", "x" * 101, "", "\u202ertl",
])
def test_injection_shaped_names_never_validate(payload):
    for action, arg in (("processes", "name"), ("services", "name"), ("events", "provider"), ("events", "log"), ("devices", "device_class")):
        if payload == "":
            continue  # empty means "not given"
        with pytest.raises(ValueError):
            validate.validate(action, {arg: payload})


@pytest.mark.parametrize("name", ["chrome", "Microsoft-Windows-Kernel-Power", "Windows PowerShell", "svchost.exe", "Spooler (x86)"])
def test_ordinary_names_pass(name):
    assert validate.validate("processes", {"name": name})[1]["name"] == name


@pytest.mark.parametrize("raw,hours", [("30m", 0.5), ("24h", 24.0), ("7d", 168.0), ("2 w", 336.0)])
def test_durations(raw, hours):
    assert validate.validate("events", {"since": raw})[1]["since"] == hours


@pytest.mark.parametrize("raw", ["0h", "91d", "-5h", "yesterday", "1e3h", "7days"])
def test_bad_durations(raw):
    with pytest.raises(ValueError):
        validate.validate("events", {"since": raw})


@pytest.mark.parametrize("raw,expected", [
    ("HKLM\\SOFTWARE\\Microsoft", "HKLM\\SOFTWARE\\Microsoft"),
    ("HKLM:\\SOFTWARE\\Microsoft\\", "HKLM\\SOFTWARE\\Microsoft"),
    ("hkey_current_user/Software/X", "HKCU\\Software\\X"),
    ("Registry::HKEY_LOCAL_MACHINE\\SYSTEM", "HKLM\\SYSTEM"),
    ("HKCU", "HKCU"),
])
def test_registry_paths_are_normalized(raw, expected):
    assert validate.validate("registry", {"path": raw})[1]["path"] == expected


@pytest.mark.parametrize("raw", ["HKCR\\x", "HKU\\.DEFAULT", "C:\\Windows", "HKLM\\..\\SAM", "HKLM\\a|b", "HKLM\\a*", "HKLM\\a\x00", "HKLM\\" + "a" * 401, ""])
def test_bad_registry_paths(raw):
    with pytest.raises(ValueError):
        validate.validate("registry", {"path": raw})


def test_help_lists_actions_and_arguments():
    assert "processes" in schema.help_text() and "registry" in schema.help_text()
    text = schema.help_text("events")
    assert "since" in text and "default 24.0" in text and "critical|error|warning|information" in text
    assert "required" in schema.help_text("registry")


def test_config_is_clamped():
    cfg = wcfg.resolve({"max_limit": 99999, "default_limit": "bogus", "ps_timeout_seconds": 1, "max_output_chars": 10})
    assert cfg["max_limit"] == 5000 and cfg["default_limit"] == 50
    assert cfg["ps_timeout_seconds"] == 5 and cfg["max_output_chars"] == 1000
    assert wcfg.resolve(None)["redact_secrets"] is True


# -- formatting ---------------------------------------------------------------------

def test_table_caps_rows_and_says_how_to_narrow():
    rows = [(i, f"proc{i}") for i in range(300)]
    out = fmt.table(["pid", "name"], rows, limit=50, total=300, hint="narrow with name=")
    assert out.splitlines()[0] == "pid | name" and "showing 50 of 300 (limit 50) - narrow with name=" in out
    assert len(out.splitlines()) == 53


def test_table_respects_the_character_cap():
    rows = [(i, "x" * 70) for i in range(500)]
    out = fmt.table(["n", "text"], rows, limit=500, max_chars=2000)
    assert len(out) <= 2000 and "output size cap" in out


def test_table_cells_cannot_break_the_layout():
    out = fmt.table(["a", "b"], [("x|y\nz", "t" * 200)], limit=5, default_width=20)
    row = out.splitlines()[2]
    assert row.count("|") == 1 and "\n" not in row and row.endswith("...")
    assert fmt.table(["a"], [], limit=5).endswith("(none)")


def test_record_and_bytes():
    assert fmt.record([("os", "Windows"), ("gpu", None), ("ram", "16 GB")]) == "os: Windows\nram: 16 GB"
    assert fmt.human_bytes(1536) == "1.5 KB" and fmt.human_bytes(5) == "5 B" and fmt.human_bytes(None) == ""


# Token-shaped test values are assembled at run time so no literal that looks
# like a real credential is ever committed (secret scanners flag those).
_SK = "sk" + "-" + "abcdefghijklmnop1234"
_AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
_GH = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123"
_JWT = "ey" + "Jhbgcioijiuzi1nij9." + "ey" + "Jzdwiioixmjm0nty3odkwin0." + "abcdefghijklmnop"
_SLACK = "xo" + "xb-" + "1234567890-abcdefghij"


@pytest.mark.parametrize("text,gone", [
    ("app.exe --password hunter2 --port 80", "hunter2"),
    ("app.exe -Password:hunter2", "hunter2"),
    ("app.exe /pass=hunter2", "hunter2"),
    ('tool --token "abc def ghi"', "abc def ghi"),
    ("db connect password=hunter2;user=x", "hunter2"),
    ('{"api_key": "' + _SK + '"}', _SK),
    ("curl -H 'Authorization: Bearer abcdef1234567890' https://x.example", "abcdef1234567890"),
    ("git clone https://user:s3cr3tpw@github.com/x/y", "s3cr3tpw"),
    ("key " + _AWS + " end", _AWS),
    ("t " + _GH + " t", _GH),
    ("jwt " + _JWT, _JWT),
    (_SLACK, _SLACK),
])
def test_secrets_are_redacted(text, gone):
    out = fmt.redact(text)
    assert gone not in out and fmt.MASK in out


@pytest.mark.parametrize("text", ["notepad.exe C:\\Users\\example\\notes.txt", "python run_ui.py --port 5000", "keyboard layout", "tokenizer ready"])
def test_ordinary_text_is_left_alone(text):
    assert fmt.redact(text) == text


def test_secret_names_mask_whole_values():
    assert fmt.mask_value("OPENAI_API_KEY", "anything") == fmt.MASK
    assert fmt.mask_value("DB_PASSWORD", "x") == fmt.MASK
    assert fmt.mask_value("PATH", "C:\\bin") == "C:\\bin"
    assert fmt.is_secret_name("AWS_SECRET_ACCESS_KEY") and not fmt.is_secret_name("TEMP")


# -- script scanner -------------------------------------------------------------------

def test_every_shipped_script_passes_the_scan():
    assert sources_ps.SCRIPTS
    for name in sources_ps.SCRIPTS:
        assert sources_ps.build_script(name)  # raises if the scan fails


@pytest.mark.parametrize("script,expect", [
    ("Remove-Item C:\\x", "Remove-Item"),
    ("Set-ItemProperty -Path HKCU:\\x -Name y -Value 1", "Set-ItemProperty"),
    ("Start-Process notepad", "Start-Process"),
    ("Stop-Service Spooler", "Stop-Service"),
    ("Invoke-Expression 'x'", "Invoke-Expression"),
    ("Invoke-WebRequest http://example.com", "Invoke-WebRequest"),
    ("Out-File x.txt", "Out-File"),
    ("New-Object Net.WebClient", "New-Object"),
    ("Add-Type -TypeDefinition 'x'", "Add-Type"),
    ("Get-Content C:\\secret.txt", "Get-Content"),
    ("Get-Credential", "Get-Credential"),
    ("Get-Service | iex", "iex"),
    ("Get-Service > out.txt", "redirection"),
    ("& 'C:\\x.exe'", "call operator"),
    ("powershell -enc AAAA", "EncodedCommand"),
    ("[System.Net.WebClient]::new()", ".NET type"),
    ("[IO.File]::Delete('x')", ".NET type"),
    ("[System.Diagnostics.Process]::Start('x')", ".NET type"),
    ("[Environment]::SetEnvironmentVariable('a','b')", "static method"),
    ("rm -Recurse x", "alias"),
    ("Get-Service; del x", "alias"),
    ("Get-Service | Select-Object Name\u00e9", "ASCII"),
    ('Get-Date "x"', "single-quoted"),
])
def test_scanner_rejects_dangerous_scripts(script, expect):
    problems = sources_ps.scan_problems(script)
    assert problems and any(expect.lower() in p.lower() for p in problems), problems


@pytest.mark.parametrize("script", [
    "Get-Service | Where-Object { $_.Status -eq 'Running' } | Select-Object Name, DisplayName | Sort-Object Name",
    "Get-WinEvent -FilterHashtable @{LogName='System'; Level=1,2} -MaxEvents 20 | ForEach-Object { $_.Id }",
    "$x = Get-Date; if ($x -gt (Get-Date)) { 'a' }",
    "Get-CimInstance Win32_OperatingSystem | Select-Object Caption | ConvertTo-Json -Compress",
    "'Remove-Item inside a string is data'",
    "'rm -rf $x'",
])
def test_scanner_accepts_read_only_scripts(script):
    assert sources_ps.scan_problems(script) == []


def test_build_script_refuses_a_script_that_fails_the_scan(monkeypatch):
    monkeypatch.setitem(sources_ps.SCRIPTS, "bad", "Remove-Item C:\\x")
    with pytest.raises(sources_ps.PsError, match="not allowed"):
        sources_ps.build_script("bad")


# -- result interpretation -------------------------------------------------------------

def test_interpret_success_and_errors():
    assert sources_ps.interpret(0, '\ufeff{"a": 1}', "") == {"a": 1}
    assert sources_ps.interpret(0, "  ", "") is None
    with pytest.raises(sources_ps.NeedsAdmin, match="standard user"):
        sources_ps.interpret(1, "", "Attempted to perform an unauthorized operation.")
    with pytest.raises(sources_ps.NeedsAdmin):
        sources_ps.interpret(1, "", "Access is denied")
    with pytest.raises(sources_ps.PsError, match="No events were found"):
        sources_ps.interpret(1, "", "No events were found\nat line 3")
    with pytest.raises(sources_ps.PsError, match="not JSON"):
        sources_ps.interpret(0, "hello", "")


# -- real PowerShell -------------------------------------------------------------------

@windows_only
def test_arguments_reach_the_script_as_inert_data():
    nasty = '"; Remove-Item -Recurse -Force C:\\nonexistent_a0w; \'`$(Get-Date) $env:USERNAME `n \u00e9\u4e2d\U0001f600 \\ \''
    result = sources_ps.run_script("selftest", {"echo": nasty}, timeout=60)
    assert result["ok"] is True
    assert result["echo"] == nasty
    assert result["psversion"][0].isdigit()


@windows_only
def test_a_slow_start_is_stopped_by_the_timeout():
    with pytest.raises(sources_ps.PsError, match="took longer"):
        sources_ps.run_script("selftest", {}, timeout=0.01)


# -- P1/P2: registry policy, tool behaviour, live actions -------------------------------

from plugins._windows_intel.helpers import sources_local


@pytest.mark.parametrize("path", [
    r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
    r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    r"HKLM\SYSTEM\CurrentControlSet\Services\Spooler",
    r"HKCU\Environment",
    r"HKCU\Control Panel\Desktop",
])
def test_registry_allowlist(path):
    assert sources_local.registry_refusal(path) == ""


@pytest.mark.parametrize("path", [
    r"HKLM\SAM", r"HKLM\SECURITY\Policy", r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa",
    r"HKLM\SOFTWARE\Microsoft\Cryptography", r"HKCU\SOFTWARE\Microsoft\Protect",
    r"HKCU\SOFTWARE\Microsoft\IdentityCRL\StoredIdentities", r"HKCU\SOFTWARE\Microsoft\Credentials",
    r"HKCU\SOFTWARE\Microsoft\Internet Explorer\IntelliForms\Storage2", r"HKLM\HARDWARE",
    r"HKLM\SOFTWAREX", "HKLM",
])
def test_registry_denylist_and_outside_roots(path):
    assert sources_local.registry_refusal(path)


class _WCtx:
    id = "ctx-wi"
    data = {}


class _WAgent:
    context = _WCtx()


@pytest.fixture
def wi(monkeypatch):
    from plugins._windows_intel.tools import windows_info as mod

    audits = []

    async def fake_audit(record):
        audits.append(record)

    monkeypatch.setattr(mod.audit_log, "append_record", fake_audit)
    monkeypatch.setattr(mod.kill_switch, "is_tripped", lambda: False)
    tool = mod.WindowsInfo(agent=_WAgent(), name="windows_info", method=None, args={}, message="", loop_data=None)
    return tool, mod, audits


@pytest.mark.asyncio
async def test_tool_reports_validation_errors_and_help(wi):
    tool, _, _ = wi
    assert "unknown action" in (await tool.execute(action="format_c")).message
    assert "may only contain" in (await tool.execute(action="processes", name="x; rm")).message
    assert "registry: read a registry key" in (await tool.execute(action="help", topic="registry")).message


@pytest.mark.asyncio
async def test_tool_refuses_while_the_kill_switch_is_tripped(wi, monkeypatch):
    tool, mod, _ = wi
    monkeypatch.setattr(mod.kill_switch, "is_tripped", lambda: True)
    monkeypatch.setattr(mod.kill_switch, "denial_message", lambda: "KILL SWITCH")
    assert (await tool.execute(action="system")).message == "KILL SWITCH"
    assert "actions" in (await tool.execute(action="help")).message  # help still works


@pytest.mark.asyncio
async def test_sensitive_reads_are_audited_without_their_output(wi, monkeypatch):
    tool, mod, audits = wi
    monkeypatch.setattr(mod.sources_local, "env", lambda args, cfg: "SECRET OUTPUT")
    monkeypatch.setattr(mod.sources_local, "network", lambda args, cfg: "net")
    await tool.execute(action="env", scope="user")
    await tool.execute(action="network")
    assert [a["action"] for a in audits] == ["env"]
    assert "SECRET OUTPUT" not in str(audits)


@pytest.mark.asyncio
async def test_security_log_says_administrator_instead_of_empty(wi):
    tool, _, _ = wi
    msg = (await tool.execute(action="events", log="Security")).message
    assert "administrator" in msg and "standard user" in msg


@pytest.mark.asyncio
async def test_a_crashing_source_does_not_end_the_turn(wi, monkeypatch):
    tool, mod, _ = wi

    def boom(args, cfg):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.sources_local, "network", boom)
    assert "failed: RuntimeError: boom" in (await tool.execute(action="network")).message


def test_windows_info_is_read_only_for_the_permission_engine():
    from plugins._permissions.helpers import rules

    assert rules.classify("windows_info", {"action": "registry"}) == "read"
    assert rules.decide("windows_info", {"action": "processes"}, "plan").decision == "allow"


@windows_only
@pytest.mark.asyncio
@pytest.mark.parametrize("action,args,expect", [
    ("system", {}, "os:"), ("processes", {"limit": 3}, "pid | name"), ("services", {"limit": 3}, "name | display name"),
    ("apps", {"limit": 3}, "name | version"), ("startup", {}, "name | where"), ("tasks", {"limit": 3}, "task | state"),
    ("events", {"since": "7d", "limit": 3}, "System log"), ("devices", {"limit": 3}, "device | class"),
    ("disks", {}, "volume | filesystem"), ("network", {}, "adapter | status"), ("ports", {"limit": 3}, "proto | local"),
    ("windows", {}, "title | process"), ("env", {"scope": "process"}, "name | value"),
    ("registry", {"path": r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "value": "CurrentBuild"}, "type: SZ"),
])
async def test_every_action_runs_on_this_machine(wi, action, args, expect):
    tool, _, _ = wi
    msg = (await tool.execute(action=action, **args)).message
    assert expect in msg, msg[:300]
    assert len(msg) <= 12000
