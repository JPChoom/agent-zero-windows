"""helpers/windows_update.py against throwaway git repos: a local "release"
repo stands in for GitHub, a clone of it for the install."""

import subprocess
import time

import pytest

from helpers import update_check
from helpers import windows_update as wu


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, name, text, message):
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    for key, value in {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
    }.items():
        monkeypatch.setenv(key, value)
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _commit(origin, "requirements.txt", "a==1\n", "first")
    _git(origin, "tag", "v1.0")
    _commit(origin, "app.py", "print(2)\n", "second")
    _git(origin, "tag", "v1.1")

    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", "--no-tags", str(origin), str(local))
    _git(local, "fetch", "-q", "origin", "refs/tags/v1.0:refs/tags/v1.0")
    _git(local, "reset", "-q", "--hard", "v1.0")

    state = tmp_path / "state.json"
    pip_calls = []
    monkeypatch.setattr(wu, "_repo_dir", lambda: str(local))
    monkeypatch.setattr(wu, "RELEASE_GIT_URL", str(origin))
    monkeypatch.setattr(wu, "_state_path", lambda: state)
    monkeypatch.setattr(wu, "_install_requirements", lambda: pip_calls.append(1))
    return {"origin": origin, "local": local, "pip": pip_calls, "state": state}


def _release(tag):
    async def fake(force=False):
        return {"tag": tag, "name": f"Release {tag}", "notes": "notes", "url": "", "published_at": ""}
    return fake


def test_version_parsing_and_comparison():
    assert wu.parse_version("v1.2") == (1, 2, 0)
    assert wu.parse_version("v1.2.1") == (1, 2, 1)
    assert wu.is_newer("v1.2.1", "v1.2") and wu.is_newer("v1.10", "v1.9")
    assert not wu.is_newer("v1.2", "v1.2.0")
    for bad in ("", "1.2", "v1", "v1.2-rc1", "v1.2; rm -rf /", "main"):
        assert wu.parse_version(bad) is None


def test_apply_fast_forwards_and_keeps_rollback_point(repos):
    before = _git(repos["local"], "rev-parse", "HEAD")
    result = wu.apply("v1.1")
    assert result == {"ok": True, "updated_to": "v1.1", "requirements_installed": False, "restart_required": True}
    assert _git(repos["local"], "describe", "--tags") == "v1.1"
    assert wu.load_state()["previous_head"] == before
    assert repos["pip"] == []


def test_apply_installs_changed_requirements(repos):
    _commit(repos["origin"], "requirements.txt", "a==1\nb==2\n", "new dep")
    _git(repos["origin"], "tag", "v1.2")
    assert wu.apply("v1.2")["requirements_installed"] is True
    assert repos["pip"] == [1]


def test_failed_requirements_install_undoes_the_update(repos, monkeypatch):
    _commit(repos["origin"], "requirements.txt", "broken\n", "bad dep")
    _git(repos["origin"], "tag", "v1.2")
    before = _git(repos["local"], "rev-parse", "HEAD")

    def fail():
        raise wu.UpdateError("pip failed")

    monkeypatch.setattr(wu, "_install_requirements", fail)
    with pytest.raises(wu.UpdateError, match="pip failed"):
        wu.apply("v1.2")
    assert _git(repos["local"], "rev-parse", "HEAD") == before
    assert not repos["state"].exists()


def test_refuses_when_tracked_files_are_modified(repos):
    (repos["local"] / "requirements.txt").write_text("edited\n", encoding="utf-8")
    with pytest.raises(wu.UpdateError, match="modified"):
        wu.apply("v1.1")
    assert (repos["local"] / "requirements.txt").read_text(encoding="utf-8") == "edited\n"
    assert wu.local_info()["modified_files"] == ["requirements.txt"]


def test_refuses_off_main(repos):
    _git(repos["local"], "checkout", "-q", "-b", "experiment")
    with pytest.raises(wu.UpdateError, match="not 'main'"):
        wu.apply("v1.1")


def test_refuses_when_local_commits_are_not_in_the_release(repos):
    _commit(repos["local"], "mine.txt", "x\n", "local work")
    mine = _git(repos["local"], "rev-parse", "HEAD")
    with pytest.raises(wu.UpdateError, match="cannot be fast-forwarded"):
        wu.apply("v1.1")
    assert _git(repos["local"], "rev-parse", "HEAD") == mine


def test_rejects_a_tag_that_is_not_a_release(repos):
    with pytest.raises(wu.UpdateError, match="Not a release tag"):
        wu.apply("main")


def test_rollback_returns_to_the_previous_commit(repos):
    before = _git(repos["local"], "rev-parse", "HEAD")
    wu.apply("v1.1")
    assert wu.rollback()["ok"] is True
    assert _git(repos["local"], "rev-parse", "HEAD") == before
    with pytest.raises(wu.UpdateError, match="no earlier version"):
        wu.rollback()


@pytest.mark.asyncio
async def test_check_reports_available_update_and_restart_pending(repos, monkeypatch):
    monkeypatch.setattr(wu, "fetch_latest_release", _release("v1.1"))
    monkeypatch.setattr(wu, "_process_started_at", lambda: time.time() - 60)
    info = await wu.check()
    assert info["current_version"] == "v1.0" and info["update_available"] and info["can_apply"]
    assert info["restart_pending"] is False and info["rollback"] is None

    wu.apply("v1.1")
    info = await wu.check()
    assert info["current_version"] == "v1.1" and not info["update_available"]
    assert info["restart_pending"] is True and info["rollback"]["to_version"] == "v1.0"


@pytest.mark.asyncio
async def test_check_explains_blockers_and_a_failed_lookup(repos, monkeypatch):
    (repos["local"] / "requirements.txt").write_text("edited\n", encoding="utf-8")
    monkeypatch.setattr(wu, "fetch_latest_release", _release("v1.1"))
    info = await wu.check()
    assert info["update_available"] and not info["can_apply"] and info["blockers"]

    async def offline(force=False):
        return None

    monkeypatch.setattr(wu, "fetch_latest_release", offline)
    info = await wu.check()
    assert info["check_failed"] and not info["update_available"]


@pytest.mark.asyncio
async def test_update_notification_only_when_a_newer_release_exists(repos, monkeypatch):
    monkeypatch.setattr(wu, "fetch_latest_release", _release("v1.1"))
    notif = (await update_check.check_version())["notification"]
    assert notif["id"] == "update_check_v1.1" and "v1.1" in notif["title"]

    monkeypatch.setattr(wu, "fetch_latest_release", _release("v1.0"))
    assert await update_check.check_version() == {}


# -- signed releases (helpers/windows_update.verify_release_tag) ---------------

import shutil  # noqa: E402

needs_ssh_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen not available")


def _key(folder, name):
    path = folder / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path)],
                   check=True, capture_output=True)
    return path


def _signed_tag(repo, tag, key):
    _git(repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={key}.pub", "tag", "-s", tag, "-m", tag)


def _trust(local, *keys):
    conf = local / "conf"
    conf.mkdir(exist_ok=True)
    lines = ["# release keys"]
    for key in keys:
        lines.append('t@example.com namespaces="git" ' + (key.parent / (key.name + ".pub")).read_text().strip())
    (conf / "release_signers").write_text("\n".join(lines) + "\n", encoding="utf-8")


@needs_ssh_keygen
def test_a_release_signed_by_the_release_key_installs(repos, tmp_path):
    key = _key(tmp_path, "release")
    _trust(repos["local"], key)
    _commit(repos["origin"], "app.py", "print(3)\n", "third")
    _signed_tag(repos["origin"], "v1.2", key)
    assert wu.apply("v1.2")["updated_to"] == "v1.2"


@needs_ssh_keygen
def test_an_unsigned_release_is_refused_and_nothing_changes(repos, tmp_path):
    _trust(repos["local"], _key(tmp_path, "release"))
    before = _git(repos["local"], "rev-parse", "HEAD")
    with pytest.raises(wu.UpdateError, match="not signed by the Agent Zero for Windows release key"):
        wu.apply("v1.1")  # a plain annotated tag, no signature
    assert _git(repos["local"], "rev-parse", "HEAD") == before


@needs_ssh_keygen
def test_a_release_signed_by_another_key_is_refused(repos, tmp_path):
    _trust(repos["local"], _key(tmp_path, "release"))
    _commit(repos["origin"], "app.py", "print(3)\n", "third")
    _signed_tag(repos["origin"], "v1.2", _key(tmp_path, "attacker"))
    before = _git(repos["local"], "rev-parse", "HEAD")
    with pytest.raises(wu.UpdateError, match="not signed"):
        wu.apply("v1.2")
    assert _git(repos["local"], "rev-parse", "HEAD") == before


@needs_ssh_keygen
def test_the_incoming_release_cannot_bring_its_own_key(repos, tmp_path):
    """The trusted keys are the installed version's, not the release's."""
    _trust(repos["local"], _key(tmp_path, "release"))
    attacker = _key(tmp_path, "attacker")
    conf = repos["origin"] / "conf"
    conf.mkdir()
    (conf / "release_signers").write_text(
        't@example.com namespaces="git" ' + (tmp_path / "attacker.pub").read_text().strip() + "\n", encoding="utf-8")
    _git(repos["origin"], "add", "conf/release_signers")
    _git(repos["origin"], "commit", "-q", "-m", "swap the key")
    _signed_tag(repos["origin"], "v1.2", attacker)
    with pytest.raises(wu.UpdateError, match="not signed"):
        wu.apply("v1.2")


def test_without_release_keys_the_check_is_skipped(repos):
    assert not (repos["local"] / "conf" / "release_signers").exists()
    assert wu.apply("v1.1")["updated_to"] == "v1.1"  # releases from before signing began


def test_packages_install_from_the_hashed_lock(repos):
    (repos["local"] / "requirements.lock.txt").write_text("a==1 \\n    --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")
    assert wu.install_command()[-3:] == ["--require-hashes", "-r", "requirements.lock.txt"]
    (repos["local"] / "requirements.lock.txt").unlink()
    assert wu.install_command()[-2:] == ["-r", "requirements.txt"]


def test_shipped_lock_has_a_hash_for_every_pin():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "requirements.lock.txt").read_text(encoding="utf-8")
    entries = [block for block in text.split("\n") if "==" in block and not block.startswith("#")]
    assert entries
    blocks = text.split("==")[1:]
    assert all("--hash=sha256:" in block.split("\n", 2)[1] for block in blocks)
