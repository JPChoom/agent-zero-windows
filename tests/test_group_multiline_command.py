"""Tests for _group_multiline_command / _write_powershell_script_invocation
in plugins/_code_execution/tools/code_execution_tool.py.

Root cause this fixes: multi-line PowerShell commands were wrapped in a
pasted `{ ... }` brace block before being sent to the terminal session.
Reproduced live against the real TTYSession/LocalInteractiveSession:
Windows PowerShell 5.1's legacy console host (PSReadLine removed) shows
'>>' after every line, including the closing brace, and never actually
executes the block - it hangs indefinitely regardless of timeout. The
same statements written to a real temp .ps1 file and invoked in one line
run instantly and correctly, including with comments and multi-line
control blocks that a naive newline-to-semicolon join would have broken.
"""

from __future__ import annotations

import os

from plugins._code_execution.tools import code_execution_tool as cet


def test_single_line_command_is_returned_unchanged():
    assert cet._group_multiline_command("Write-Host hi", powershell=True) == "Write-Host hi"
    assert cet._group_multiline_command("echo hi", powershell=False) == "echo hi"


def test_posix_multiline_still_uses_brace_grouping():
    result = cet._group_multiline_command("echo a\necho b", powershell=False)
    assert result == "{\necho a\necho b\n}"


def test_powershell_multiline_writes_a_temp_script_and_returns_one_line_invocation():
    body = "$x = 1\nWrite-Host $x"
    result = cet._group_multiline_command(body, powershell=True)

    # Must be a single line - no embedded newlines, which is exactly what
    # sidesteps the '>>' continuation-prompt hang.
    assert "\n" not in result
    assert result.startswith("& '")
    assert "Remove-Item -LiteralPath '" in result
    assert "-ErrorAction SilentlyContinue" in result

    # The invoked path must be a real, existing .ps1 file containing the
    # exact original multi-line body.
    path = result.split("'", 2)[1]
    assert os.path.exists(path)
    assert path.endswith(".ps1")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        assert content == body
    finally:
        os.unlink(path)


def test_powershell_script_file_is_written_with_utf8_bom():
    # Windows PowerShell 5.1 (not Core) assumes the system codepage for a
    # .ps1 with no BOM, so a plain utf-8 file with non-ASCII content would
    # misdecode - the BOM is what makes PowerShell read it as UTF-8.
    body = "Write-Host 'café'"
    result = cet._group_multiline_command(body + "\nWrite-Host 'done'", powershell=True)
    path = result.split("'", 2)[1]
    try:
        with open(path, "rb") as f:
            raw = f.read()
        assert raw.startswith(b"\xef\xbb\xbf")
    finally:
        os.unlink(path)


def test_powershell_script_preserves_comments_and_multiline_blocks():
    # A naive newline -> ';' join would silently break this (comments
    # extend to end of line, swallowing everything joined after them).
    body = (
        "# a comment\n"
        "foreach ($i in 1..3) {\n"
        "    Write-Host $i\n"
        "}"
    )
    result = cet._group_multiline_command(body, powershell=True)
    path = result.split("'", 2)[1]
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        assert content == body
    finally:
        os.unlink(path)
