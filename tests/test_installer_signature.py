"""installer/install.ps1 installs only signed releases with hash-checked packages."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "installer" / "install.ps1").read_text(encoding="utf-8")


def _signer_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def test_the_pinned_key_is_the_release_key():
    pinned = re.search(r"\$ReleaseSigner = '([^']+)'", SCRIPT).group(1)
    assert pinned in _signer_lines((ROOT / "conf" / "release_signers").read_text(encoding="utf-8"))


def test_every_checkout_is_verified_first():
    checkouts = [m.start() for m in re.finditer(r"checkout --quiet", SCRIPT)]
    assert len(checkouts) == 2
    for position in checkouts:
        assert "Confirm-ReleaseTag $Version" in SCRIPT[max(0, position - 400):position]
    assert "--no-checkout" in SCRIPT  # a fresh clone is not checked out before the check


def test_only_the_hash_checked_lock_is_installed():
    assert "--require-hashes -r $reqs" in SCRIPT
    assert 'Join-Path $app "requirements.txt"' not in SCRIPT
    assert "has no requirements.lock.txt" in SCRIPT


def _git(repo, *args, env=None):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env)


@pytest.mark.skipif(shutil.which("git") is None or shutil.which("powershell.exe") is None, reason="needs git and PowerShell")
def test_an_unsigned_tag_is_refused_by_the_real_function(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "tag", "-a", "v9.9", "-m", "unsigned")
    # Load only the helpers from the script, then check the tag.
    start = SCRIPT.index("function Step(")
    end = SCRIPT.index("function Find-Python312")
    helpers = SCRIPT[start:end]
    script = tmp_path / "check.ps1"
    script.write_text(helpers + f"\nSet-Location '{repo}'\nConfirm-ReleaseTag v9.9\nWrite-Host 'VERIFIED'\n", encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 1
    assert "not signed" in result.stdout and "VERIFIED" not in result.stdout


@pytest.mark.skipif(shutil.which("git") is None or shutil.which("powershell.exe") is None, reason="needs git and PowerShell")
def test_a_real_signed_release_tag_passes(tmp_path):
    tag = "v1.5.5"
    if _git(ROOT, "rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode != 0:
        pytest.skip("release tags are not in this checkout")
    start = SCRIPT.index("function Step(")
    end = SCRIPT.index("function Find-Python312")
    script = tmp_path / "check.ps1"
    script.write_text(SCRIPT[start:end] + f"\nSet-Location '{ROOT}'\nConfirm-ReleaseTag {tag}\nWrite-Host 'VERIFIED'\n", encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "VERIFIED" in result.stdout
