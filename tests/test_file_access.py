"""helpers/file_access.py: the File Browser's access policy. A throwaway
folder tree stands in for the A0 install, the workdir, the system drive and
other drives."""

import os
import subprocess

import pytest

from helpers import file_access as fa

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows path rules")


def _cfg(scope="a0_root", remote_scope="a0_root", other=False, removable=False):
    return {
        "file_browser_scope": scope,
        "file_browser_remote_scope": remote_scope,
        "file_browser_allow_other_drives": other,
        "file_browser_allow_removable_drives": removable,
    }


@pytest.fixture
def tree(tmp_path, monkeypatch):
    t = tmp_path
    base, system, fixed, usb = t / "a0", t / "sysdrive", t / "ddrive", t / "usbstick"
    for p in (base / "usr" / "workdir", base / "helpers", system / "Users", fixed, usb, t / "outside"):
        p.mkdir(parents=True, exist_ok=True)
    (base / "README.md").write_text("readme")
    (base / "usr" / "workdir" / "notes.txt").write_text("notes")
    (t / "outside" / "private.txt").write_text("private")
    monkeypatch.setattr(fa, "a0_base", lambda: base)
    monkeypatch.setattr(fa, "workdir", lambda: base / "usr" / "workdir")
    monkeypatch.setattr(fa, "system_drive_root", lambda: str(system) + "\\")
    monkeypatch.setattr(fa, "list_drives", lambda force=False: [
        {"root": str(system) + "\\", "kind": "system"},
        {"root": str(fixed) + "\\", "kind": "fixed"},
        {"root": str(usb) + "\\", "kind": "removable"},
    ])
    return t


def _allowed(policy, path):
    try:
        fa.resolve(path, policy, must_exist=False)
        return True
    except fa.AccessDenied:
        return False


# -- scopes -------------------------------------------------------------------

def test_scopes_from_narrowest_to_widest(tree):
    usr = fa.policy_for(False, _cfg("usr"))
    a0 = fa.policy_for(False, _cfg("a0_root"))
    full = fa.policy_for(False, _cfg("full"))
    readme, notes, users = tree / "a0" / "README.md", tree / "a0" / "usr" / "workdir" / "notes.txt", tree / "sysdrive" / "Users"
    assert [_allowed(usr, p) for p in (notes, readme, users)] == [True, False, False]
    assert [_allowed(a0, p) for p in (notes, readme, users)] == [True, True, False]
    assert [_allowed(full, p) for p in (notes, readme, users)] == [True, True, True]


def test_other_drives_need_their_toggles(tree):
    d, usb = tree / "ddrive", tree / "usbstick"
    assert not _allowed(fa.policy_for(False, _cfg("full")), d)
    assert _allowed(fa.policy_for(False, _cfg("full", other=True)), d)
    assert not _allowed(fa.policy_for(False, _cfg("full", other=True)), usb)
    assert _allowed(fa.policy_for(False, _cfg("a0_root", removable=True)), usb)


def test_workdir_is_always_reachable_even_outside_the_install(tree, monkeypatch):
    elsewhere = tree / "outside"
    monkeypatch.setattr(fa, "workdir", lambda: elsewhere)
    assert _allowed(fa.policy_for(True, _cfg("usr", "usr")), elsewhere / "private.txt")


# -- remote cap ---------------------------------------------------------------

def test_remote_sessions_get_the_narrower_scope_and_no_drives(tree):
    cfg = _cfg("full", "a0_root", other=True, removable=True)
    remote = fa.policy_for(True, cfg)
    assert remote.scope == "a0_root"
    assert not _allowed(remote, tree / "sysdrive" / "Users")
    assert not _allowed(remote, tree / "ddrive")
    assert not _allowed(remote, tree / "usbstick")
    assert fa.policy_for(True, _cfg("usr", "a0_root")).scope == "usr"  # never wider than local


def test_remote_same_follows_local_including_drives(tree):
    remote = fa.policy_for(True, _cfg("full", "same", other=True))
    assert remote.scope == "full" and _allowed(remote, tree / "ddrive")


def test_widening_is_detected_for_local_and_remote(tree):
    assert fa.widens(_cfg("full"), _cfg("a0_root"))
    assert fa.widens(_cfg("a0_root", "same", other=True), _cfg("a0_root", "same"))
    assert fa.widens(_cfg("full", "same"), _cfg("full", "a0_root"))  # remote only
    assert not fa.widens(_cfg("usr"), _cfg("a0_root"))
    assert not fa.widens(_cfg("a0_root", "usr"), _cfg("a0_root", "a0_root"))


# -- path shapes and escapes --------------------------------------------------

@pytest.mark.parametrize("raw", [
    "", "/notes.txt", "notes.txt", r"..\a0", r"\\server\share\x", r"\\?\C:\Windows",
    r"\\.\PhysicalDrive0", "C:\\a0\\README.md:stream", r"C:\x\NUL", r"C:\x\con.txt\y", "C:\\x\0y",
])
def test_unsupported_path_shapes_are_refused(tree, raw):
    with pytest.raises(fa.AccessDenied):
        fa.resolve(raw, fa.policy_for(False, _cfg("full")), must_exist=False)


def test_sibling_with_a_common_prefix_is_outside(tree):
    (tree / "a0-evil").mkdir()
    policy = fa.policy_for(False, _cfg("a0_root"))
    assert not _allowed(policy, tree / "a0-evil")
    assert not _allowed(policy, str(tree / "a0" / "usr" / ".." / ".." / "a0-evil"))


def test_case_and_slashes_do_not_matter(tree):
    policy = fa.policy_for(False, _cfg("a0_root"))
    mixed = str(tree / "A0" / "README.md").upper().replace("\\", "/")
    assert fa.resolve(mixed, policy).name.lower() == "readme.md"


def test_a_junction_pointing_outside_is_refused(tree):
    link = tree / "a0" / "usr" / "workdir" / "escape"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(tree / "outside")], check=True, capture_output=True)
    policy = fa.policy_for(False, _cfg("a0_root"))
    with pytest.raises(fa.AccessDenied):
        fa.resolve(link / "private.txt", policy)


# -- protected files ----------------------------------------------------------

@pytest.mark.parametrize("rel", [
    ".env", "usr/.env", "usr/secrets.env", "usr/permissions_bypass.json",
    "usr/security_audit.jsonl", "usr/security_audit.3.jsonl",
    "usr/plugins/_oauth/codex/auth.json", "usr/plugins/_oauth",
    "usr/plugins/_discord_integration/config.json",
    "usr/agents/agent0/plugins/_email_integration/config.json",
    "usr/whatsapp/bridge-runtime/session/creds.json",
    "usr/projects/p/.a0proj/secrets.env",
    "usr/projects/p/.a0proj/plugins/_slack_integration/config.json",
])
def test_a0_secrets_are_protected_in_every_mode(tree, rel):
    path = tree / "a0" / rel
    assert fa.is_protected(path)
    assert not _allowed(fa.policy_for(False, _cfg("full")), path)


@pytest.mark.parametrize("rel", [
    "usr/workdir/myapp/.env", "usr/workdir/site/plugins/x/config.json",
    "usr/settings.json", "usr/workdir/notes.txt", "README.md",
])
def test_ordinary_files_are_not_protected(tree, rel):
    assert not fa.is_protected(tree / "a0" / rel)


def test_external_project_secrets_are_protected(tree):
    assert fa.is_protected(tree / "outside" / "proj" / ".a0proj" / "secrets.env")
    assert not fa.is_protected(tree / "outside" / "proj" / "secrets.env")


def test_contains_protected_finds_nested_secrets(tree):
    (tree / "a0" / "usr" / "plugins" / "_oauth").mkdir(parents=True)
    assert fa.contains_protected(tree / "a0" / "usr")
    assert not fa.contains_protected(tree / "a0" / "usr" / "workdir")


# -- new names ----------------------------------------------------------------

@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "a:b", "x?", "CON", "nul.txt", "com1", "trail.", "trail ", "x" * 256])
def test_invalid_windows_names_are_refused(tree, name):
    with pytest.raises(fa.AccessDenied):
        fa.resolve_new(tree / "a0" / "usr" / "workdir", name, fa.policy_for(False, _cfg()))


def test_resolve_new_refuses_creating_a_protected_file(tree):
    with pytest.raises(fa.AccessDenied):
        fa.resolve_new(tree / "a0" / "usr", "secrets.env", fa.policy_for(False, _cfg()))
    assert fa.resolve_new(tree / "a0" / "usr" / "workdir", "ok.txt", fa.policy_for(False, _cfg())).name == "ok.txt"


def test_real_drive_listing_includes_the_system_drive():
    drives = fa.list_drives(force=True)
    assert any(d["kind"] == "system" for d in drives)
    assert all(set(d) >= {"root", "label", "kind", "total", "free"} for d in drives)
