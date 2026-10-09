"""helpers/file_manager.py and its API: File Browser operations on real
Windows paths, always behind helpers/file_access.py."""

import io
import os
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from helpers import file_access as fa
from helpers import file_manager as fm

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows path rules")


@pytest.fixture
def env(tmp_path, monkeypatch):
    base = tmp_path / "a0"
    work = base / "usr" / "workdir"
    (work / "docs").mkdir(parents=True)
    (base / "usr" / "plugins" / "_oauth").mkdir(parents=True)
    (base / "usr" / "plugins" / "_oauth" / "token.json").write_text("SECRET-TOKEN")
    (base / "usr" / ".env").write_text("AUTH_PASSWORD=SECRET")
    (work / "a.txt").write_text("alpha")
    (work / "docs" / "b.md").write_text("# beta")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "private.txt").write_text("PRIVATE")
    monkeypatch.setattr(fa, "a0_base", lambda: base)
    monkeypatch.setattr(fa, "workdir", lambda: work)
    monkeypatch.setattr(fa, "list_drives", lambda force=False: [])
    policy = fa.policy_for(False, {
        "file_browser_scope": "a0_root", "file_browser_remote_scope": "a0_root",
        "file_browser_allow_other_drives": False, "file_browser_allow_removable_drives": False,
    })
    return SimpleNamespace(base=base, work=work, out=tmp_path / "outside", policy=policy)


def test_listing_hides_protected_and_hidden_files(env):
    subprocess.run(["attrib", "+h", str(env.work / "a.txt")], check=True)
    listing = fm.list_dir(str(env.base / "usr"), env.policy)
    names = {e["name"] for e in listing["entries"]}
    assert ".env" not in names and "workdir" in names
    work = fm.list_dir(str(env.work), env.policy)
    assert [e["name"] for e in work["entries"]] == ["docs"] and work["hidden_count"] == 1
    shown = fm.list_dir(str(env.work), env.policy, show_hidden=True)
    assert {e["name"] for e in shown["entries"]} == {"docs", "a.txt"}
    assert work["parent"] == str(env.base / "usr")


def test_parent_is_empty_at_the_edge_of_the_allowed_area(env):
    assert fm.list_dir(str(env.base), env.policy)["parent"] == ""


@pytest.mark.parametrize("raw, folder, select", [
    ("", "work", ""), ("$WORK_DIR", "work", ""), ("/a0/usr/workdir", "work", ""),
    ("/a0/usr", "usr", ""), ("docs", "docs", ""), ("/docs/b.md", "docs", "b.md"), ("a.txt", "work", "a.txt"),
])
def test_locate_translates_legacy_paths(env, raw, folder, select):
    where = {"work": env.work, "usr": env.base / "usr", "docs": env.work / "docs"}
    result = fm.locate(raw, env.policy)
    assert result["folder"] == str(where[folder])
    assert result["select"] == (str(where[folder] / select) if select else "")


def test_locate_still_enforces_the_policy(env):
    with pytest.raises(fa.AccessDenied):
        fm.locate(str(env.out), env.policy)


def test_create_rename_and_name_conflicts(env):
    folder = fm.mkdir(str(env.work), "New folder", env.policy)
    with pytest.raises(fm.FileOpError):
        fm.mkdir(str(env.work), "New folder", env.policy)
    renamed = fm.rename(folder, "Reports", env.policy)
    assert os.path.isdir(renamed) and not os.path.exists(folder)
    fm.new_file(renamed, "x.txt", env.policy)
    with pytest.raises(fm.FileOpError):
        fm.rename(str(env.work / "a.txt"), "docs", env.policy)


def test_folders_holding_protected_files_cannot_be_changed(env):
    usr = str(env.base / "usr")
    with pytest.raises(fm.FileOpError):
        fm.rename(str(env.base / "usr" / "plugins"), "x", env.policy)
    with pytest.raises(fm.FileOpError):
        fm.delete([str(env.base / "usr" / "plugins")], env.policy, permanent=True)
    with pytest.raises(fm.FileOpError):
        fm.transfer([str(env.base / "usr" / "plugins")], str(env.work), env.policy, move=False)
    assert os.path.isdir(usr)


def test_top_folders_and_their_parents_cannot_be_deleted(env):
    for path in (env.work, env.base / "usr"):
        with pytest.raises(fm.FileOpError):
            fm.delete([str(path)], env.policy, permanent=True)


def test_delete_goes_to_the_recycle_bin_unless_permanent(env, monkeypatch):
    recycled = []
    monkeypatch.setattr(fm, "_recycle", lambda paths: recycled.extend(paths))
    result = fm.delete([str(env.work / "a.txt")], env.policy)
    assert result["recycled"] is True and recycled == [env.work / "a.txt"]
    result = fm.delete([str(env.work / "docs")], env.policy, permanent=True)
    assert result["recycled"] is False and not (env.work / "docs").exists()


def test_removable_drives_delete_outright(env, monkeypatch):
    monkeypatch.setattr(fm, "_drive_kind", lambda path: "removable")
    monkeypatch.setattr(fm, "_recycle", lambda paths: pytest.fail("no Recycle Bin on removable drives"))
    assert fm.delete([str(env.work / "a.txt")], env.policy)["recycled"] is False


def test_copy_and_move_with_explorer_style_names(env):
    copied = fm.transfer([str(env.work / "a.txt")], str(env.work), env.policy, move=False)
    assert os.path.basename(copied[0]) == "a (2).txt"
    moved = fm.transfer([str(env.work / "a.txt")], str(env.work / "docs"), env.policy, move=True)
    assert moved == [str(env.work / "docs" / "a.txt")] and not (env.work / "a.txt").exists()
    with pytest.raises(fm.FileOpError):
        fm.transfer([str(env.work / "docs")], str(env.work / "docs"), env.policy, move=True)
    with pytest.raises(fa.AccessDenied):
        fm.transfer([str(env.work / "docs")], str(env.out), env.policy, move=True)


def test_upload_never_overwrites_unless_asked(env):
    first = fm.save_upload(str(env.work), "a.txt", io.BytesIO(b"new"), env.policy)
    assert os.path.basename(first) == "a (2).txt" and (env.work / "a.txt").read_text() == "alpha"
    fm.save_upload(str(env.work), "a.txt", io.BytesIO(b"replaced"), env.policy, overwrite=True)
    assert (env.work / "a.txt").read_text() == "replaced"
    assert os.path.basename(fm.save_upload(str(env.work), r"..\..\evil.txt", io.BytesIO(b"x"), env.policy)) == "evil.txt"
    assert (env.work / "evil.txt").exists()
    with pytest.raises(fa.AccessDenied):
        fm.save_upload(str(env.base / "usr"), ".env", io.BytesIO(b"x"), env.policy, overwrite=True)
    assert not list(env.work.glob("*.part-*"))


def test_text_round_trip_keeps_encoding_and_detects_changes(env):
    path = env.work / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbfcaf\xc3\xa9\r\n")
    loaded = fm.read_text(str(path), env.policy)
    assert loaded["content"] == "café\n" and loaded["encoding"] == "utf-8-sig" and loaded["newline"] == "\r\n"
    # The browser sends "\n" line endings back; the file keeps CRLF.
    fm.write_text(str(path), loaded["content"] + "more\n", env.policy, loaded["encoding"], loaded["modified"], loaded["newline"])
    assert path.read_bytes() == b"\xef\xbb\xbfcaf\xc3\xa9\r\nmore\r\n"
    unix = env.work / "unix.sh"
    unix.write_bytes(b"echo 1\necho 2\n")
    assert fm.read_text(str(unix), env.policy)["newline"] == "\n"
    os.utime(path, (1, 1))
    with pytest.raises(fm.FileOpError, match="changed on disk"):
        fm.write_text(str(path), "x", env.policy, "utf-8", loaded["modified"])
    (env.work / "bin.dat").write_bytes(b"\0\1\2")
    with pytest.raises(fm.FileOpError, match="binary"):
        fm.read_text(str(env.work / "bin.dat"), env.policy)


def test_zip_skips_protected_files_and_links_that_leave(env):
    link = env.base / "usr" / "workdir" / "docs" / "escape"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(env.out)], check=True, capture_output=True)
    path, name = fm.zip_selection([str(env.base / "usr")], env.policy)
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            blob = b"".join(zf.read(n) for n in names if not n.endswith("/"))
        assert name == "usr.zip"
        assert "usr/workdir/a.txt" in names and "usr/workdir/docs/b.md" in names
        assert b"SECRET" not in blob and b"PRIVATE" not in blob
    finally:
        os.remove(path)


# -- API and settings -----------------------------------------------------------

def test_main_settings_save_cannot_change_file_access(monkeypatch):
    from helpers import settings

    current = settings.get_settings()
    merged = settings.convert_in({**current, "file_browser_scope": "full", "file_browser_allow_removable_drives": True})
    assert merged["file_browser_scope"] == current["file_browser_scope"]
    assert merged["file_browser_allow_removable_drives"] == current["file_browser_allow_removable_drives"]


@pytest.fixture
def security_api(monkeypatch, env):
    from api import security_settings as api
    from plugins._permissions.helpers import bypass_lock

    store = {"file_browser_scope": "a0_root", "file_browser_remote_scope": "a0_root",
             "file_browser_allow_other_drives": False, "file_browser_allow_removable_drives": False}
    monkeypatch.setattr(fa, "read_settings", lambda: dict(store))
    monkeypatch.setattr(api.settings_helper, "set_settings_delta", lambda delta: store.update(delta))
    monkeypatch.setattr(api.access_control, "audit", lambda *a, **k: None)
    monkeypatch.setattr(api.SecuritySettings, "_state", lambda self, is_local, my_ip: {"ok": True})
    monkeypatch.setattr(bypass_lock, "is_set", lambda: True)
    monkeypatch.setattr(bypass_lock, "verify", lambda pw: pw == "right-password")
    bypass_lock.throttle.__init__()
    handler = api.SecuritySettings.__new__(api.SecuritySettings)
    return SimpleNamespace(store=store, call=lambda local, **kw: handler._save_file_access(
        kw.get("config", {}), local, "" if local else "203.0.113.9", kw.get("password")))


def test_widening_remotely_needs_the_bypass_password(security_api):
    wider = {"config": {"file_browser_scope": "full"}}
    assert security_api.call(False, **wider)["needs_password"] is True
    assert security_api.store["file_browser_scope"] == "a0_root"
    assert security_api.call(False, **wider, password="wrong")["error"] == "Wrong Bypass password."
    assert security_api.call(False, **wider, password="right-password")["ok"] is True
    assert security_api.store["file_browser_scope"] == "full"


def test_narrowing_remotely_and_any_change_locally_need_no_password(security_api):
    assert security_api.call(False, config={"file_browser_scope": "usr"})["ok"] is True
    assert security_api.call(True, config={"file_browser_scope": "full", "file_browser_remote_scope": "same"})["ok"] is True


def test_wrong_passwords_lock_out_across_endpoints(security_api):
    from plugins._permissions.helpers import bypass_lock

    for _ in range(bypass_lock.throttle.MAX_FAILURES):
        security_api.call(False, config={"file_browser_scope": "full"}, password="wrong")
    result = security_api.call(False, config={"file_browser_scope": "full"}, password="right-password")
    assert "Too many" in result["error"]
    assert bypass_lock.check("right-password", "203.0.113.9") == "locked"  # the Bypass unlock shares it


# -- legacy path forms, change events, the old download URL ----------------------

@pytest.mark.parametrize("raw, expected", [
    ("", "work"), ("$WORK_DIR", "work"), ("/a0/usr/uploads/x y.pdf", "base:usr/uploads/x y.pdf"),
    ("file:///a0/usr/workdir/a.txt", "base:usr/workdir/a.txt"), ("docs/b.md", "work:docs/b.md"),
    ("file:///C:/Temp/x%20y.txt", r"C:/Temp/x y.txt"), (r"D:\data\z.csv", r"D:\data\z.csv"),
])
def test_translate_handles_every_path_form_other_features_send(env, raw, expected):
    if expected == "work":
        want = str(env.work)
    elif expected.startswith("base:"):
        want = str(env.base.joinpath(*expected[5:].split("/")))
    elif expected.startswith("work:"):
        want = str(env.work.joinpath(*expected[5:].split("/")))
    else:
        want = expected
    assert fm.translate(raw) == want


@pytest.mark.asyncio
async def test_changes_announce_workdir_file_mutation_after(env, monkeypatch):
    from api import file_manager as api

    events = []

    async def fake_call(point, agent=None, data=None, **kwargs):
        events.append((point, data))

    monkeypatch.setattr(api.extension, "call_extensions_async", fake_call)
    monkeypatch.setattr(api, "caller", lambda request: (False, "local"))
    monkeypatch.setattr(api.fa, "policy_for", lambda remote: env.policy)
    monkeypatch.setattr(api.access_control, "audit", lambda *a, **k: None)
    handler = api.FileManager.__new__(api.FileManager)

    result = await handler.process({"action": "rename", "path": str(env.work / "a.txt"), "name": "b.txt"}, None)
    assert result["ok"]
    point, data = events[-1]
    assert point == "workdir_file_mutation_after" and data["action"] == "rename"
    assert data["paths"] == [str(env.work / "a.txt"), str(env.work / "b.txt")]

    await handler.process({"action": "mkdir", "path": str(env.work), "name": "New"}, None)
    assert events[-1][1]["action"] == "create-folder"
    await handler.process({"action": "list", "path": str(env.work)}, None)  # reads announce nothing
    assert len(events) == 2


@pytest.mark.asyncio
async def test_old_download_url_goes_through_the_policy(env, monkeypatch):
    from flask import Flask
    from api import download_work_dir_file as legacy
    from api import file_manager_download as dl

    monkeypatch.setattr(dl, "caller", lambda request: (False, "local"))
    monkeypatch.setattr(dl.fa, "policy_for", lambda remote: env.policy)
    monkeypatch.setattr(dl.access_control, "audit", lambda *a, **k: None)
    handler = legacy.DownloadFile.__new__(legacy.DownloadFile)
    app = Flask(__name__)

    async def get(path):
        with app.test_request_context("/api/download_work_dir_file", query_string={"path": path}):
            from flask import request
            return await handler.process({}, request)

    ok = await get("/a0/usr/workdir/a.txt")
    assert ok.status_code == 200 and b"".join(ok.response) == b"alpha"
    assert (await get("/a0/usr/.env")).status_code == 403
    assert (await get(str(env.out / "private.txt"))).status_code == 403


# -- folder uploads ----------------------------------------------------------------

def test_ensure_dir_builds_nested_folders_and_keeps_existing_ones(env):
    deepest = fm.ensure_dir(str(env.work), "Photos/2026/Trip", env.policy)
    assert deepest == str(env.work / "Photos" / "2026" / "Trip") and os.path.isdir(deepest)
    assert fm.ensure_dir(str(env.work), r"Photos\2026", env.policy) == str(env.work / "Photos" / "2026")
    (env.work / "Photos" / "clash").write_text("x")
    with pytest.raises(fm.FileOpError, match="exists as a file"):
        fm.ensure_dir(str(env.work), "Photos/clash/inner", env.policy)


@pytest.mark.parametrize("rel", ["../escape", "a/../../escape", "ok/./x", "a/con/b", "a/b:c", "x/" * 70 + "y"])
def test_ensure_dir_refuses_escapes_and_invalid_names(env, rel):
    with pytest.raises((fa.AccessDenied, fm.FileOpError)):
        fm.ensure_dir(str(env.work), rel, env.policy)
    assert not (env.work.parent / "escape").exists()


def test_ensure_dir_cannot_create_protected_names(env):
    with pytest.raises(fa.AccessDenied):
        fm.ensure_dir(str(env.base / "usr" / "plugins"), "_oauth/x", env.policy)


@pytest.mark.asyncio
async def test_upload_endpoint_keeps_folder_structure_and_empty_folders(env, monkeypatch):
    from flask import Flask
    from werkzeug.datastructures import FileStorage, MultiDict
    from api import file_manager_upload as up

    events = []

    async def fake_announce(action, paths, current=""):
        events.append((action, paths))

    monkeypatch.setattr(up, "caller", lambda request: (False, "local"))
    monkeypatch.setattr(up.fa, "policy_for", lambda remote: env.policy)
    monkeypatch.setattr(up.access_control, "audit", lambda *a, **k: None)
    monkeypatch.setattr(up, "announce_change", fake_announce)
    handler = up.FileManagerUpload.__new__(up.FileManagerUpload)
    app = Flask(__name__)

    form = MultiDict([
        ("path", str(env.work)),
        ("dirs[]", "Album"), ("dirs[]", "Album/empty"), ("dirs[]", "Album/sub"),
        ("relpaths[]", "Album/cover.jpg"), ("relpaths[]", "Album/sub/note.txt"), ("relpaths[]", "Album/../../evil.txt"),
    ])
    files = MultiDict([
        ("files[]", FileStorage(io.BytesIO(b"jpg"), filename="cover.jpg")),
        ("files[]", FileStorage(io.BytesIO(b"txt"), filename="note.txt")),
        ("files[]", FileStorage(io.BytesIO(b"bad"), filename="evil.txt")),
    ])
    with app.test_request_context("/api/file_manager_upload", method="POST", data={**form.to_dict(flat=False), **files.to_dict(flat=False)}, content_type="multipart/form-data"):
        from flask import request
        result = await handler.process({}, request)

    album = env.work / "Album"
    assert (album / "cover.jpg").read_bytes() == b"jpg"
    assert (album / "sub" / "note.txt").read_bytes() == b"txt"
    assert (album / "empty").is_dir()
    assert [f["name"] for f in result["failed"]] == ["Album/../../evil.txt"]
    assert not (env.base / "evil.txt").exists() and not (env.work.parent / "evil.txt").exists()
    assert events and events[0][0] == "upload"
