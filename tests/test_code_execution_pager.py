"""Regression tests for issue #1697.

Pagers (more/less) must be disabled in the non-interactive shells created by the
code execution tool: without user input they block forever and spin at 100% CPU.
"""

from plugins._code_execution.helpers import shell_local, shell_ssh


def test_local_env_disables_pagers_and_preserves_existing():
    env = shell_local.disable_pagers_in_env({"PATH": "/usr/bin", "PAGER": "less"})
    assert env["PAGER"] == "cat"
    assert env["GIT_PAGER"] == "cat"
    # pre-existing keys are preserved
    assert env["PATH"] == "/usr/bin"


def test_local_env_defaults_to_environ():
    env = shell_local.disable_pagers_in_env()
    assert env["PAGER"] == "cat"
    assert env["GIT_PAGER"] == "cat"


def test_local_env_does_not_mutate_input():
    src = {"PATH": "/usr/bin"}
    shell_local.disable_pagers_in_env(src)
    assert src == {"PATH": "/usr/bin"}


def test_ssh_command_disables_pagers():
    assert "GIT_PAGER=cat" in shell_ssh.PAGER_DISABLE_COMMAND
    assert "PAGER=cat" in shell_ssh.PAGER_DISABLE_COMMAND
