"""The llama.cpp server plugin around the supervisor: download safety, the
API's local-only download, and autostart. No network: release data and
archives are built in the test."""

from __future__ import annotations

import asyncio
import io
import types
import zipfile

import pytest

from plugins._llama_server.helpers import download, supervisor

DIGEST = "sha256:" + "a" * 64
BASE = "https://github.com/ggml-org/llama.cpp/releases/download/b9999/"


def _asset(name, digest=DIGEST, url=None, size=1000):
    return {"name": name, "browser_download_url": url or BASE + name, "digest": digest, "size": size}


RELEASE = {
    "tag_name": "b9999",
    "assets": [
        _asset("llama-b9999-bin-win-cpu-x64.zip"),
        _asset("llama-b9999-bin-win-cuda-12.4-x64.zip"),
        _asset("cudart-llama-bin-win-cuda-12.4-x64.zip"),
        _asset("llama-b9999-bin-win-vulkan-x64.zip"),
        _asset("llama-b9999-bin-macos-arm64.zip"),
    ],
}


def test_variants_pick_the_right_assets():
    assert [a["name"] for a in download.select_assets(RELEASE, "cpu")] == ["llama-b9999-bin-win-cpu-x64.zip"]
    assert [a["name"] for a in download.select_assets(RELEASE, "cuda")] == [
        "llama-b9999-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]
    with pytest.raises(download.DownloadError):
        download.select_assets(RELEASE, "rocm-something")


def test_the_newest_release_with_the_build_is_used_prereleases_included():
    # Upstream ships every build as a pre-release; an unrelated newer release
    # without Windows assets must not be picked.
    library = {"tag_name": "v0.6.0", "prerelease": False, "assets": [_asset("python-bindings.tar.gz")]}
    draft = {"tag_name": "b10000", "draft": True, "assets": RELEASE["assets"]}
    build = {**RELEASE, "tag_name": "b9999", "prerelease": True}
    release, assets = download.newest_release_with([draft, library, build], "vulkan")
    assert release["tag_name"] == "b9999" and assets[0]["name"] == "llama-b9999-bin-win-vulkan-x64.zip"


def test_rocm_build_is_available():
    release = {"tag_name": "b1", "assets": [_asset("llama-b1-bin-win-rocm-10.0-x64.zip")]}
    assert download.select_assets(release, "rocm")[0]["name"] == "llama-b1-bin-win-rocm-10.0-x64.zip"


def test_an_asset_without_a_published_digest_is_refused():
    release = {"tag_name": "x", "assets": [_asset("llama-x-bin-win-cpu-x64.zip", digest=None)]}
    with pytest.raises(download.DownloadError, match="no published SHA-256"):
        download.select_assets(release, "cpu")


def test_an_asset_hosted_elsewhere_is_refused():
    release = {"tag_name": "x", "assets": [_asset("llama-x-bin-win-cpu-x64.zip", url="https://evil.example/llama.zip")]}
    with pytest.raises(download.DownloadError, match="Unexpected download location"):
        download.select_assets(release, "cpu")


def test_a_wrong_checksum_is_refused(monkeypatch):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(download.urllib.request, "urlopen", lambda req, timeout=0: Resp(b"tampered"))
    with pytest.raises(download.DownloadError, match="mismatch"):
        download._verified_bytes({"name": "x.zip", "url": BASE + "x.zip", "sha256": "0" * 64})


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extract_installs_server_and_cuda_runtime_together(tmp_path):
    target = tmp_path / "bin"
    server = _zip({"build/bin/llama-server.exe": b"exe", "build/bin/ggml.dll": b"dll"})
    cudart = _zip({"cudart64_12.dll": b"cuda"})
    download.extract([server, cudart], str(target))
    assert (target / "llama-server.exe").read_bytes() == b"exe"
    assert (target / "ggml.dll").exists() and (target / "cudart64_12.dll").exists()
    assert not (tmp_path / "bin.new").exists()


def test_extract_refuses_path_traversal(tmp_path):
    evil = _zip({"llama-server.exe": b"exe", "../../escape.dll": b"x"})
    with pytest.raises(download.DownloadError, match="escapes"):
        download.extract([evil], str(tmp_path / "bin"))
    assert not (tmp_path.parent / "escape.dll").exists()


def test_extract_requires_the_server(tmp_path):
    with pytest.raises(download.DownloadError, match="does not contain"):
        download.extract([_zip({"readme.txt": b"x"})], str(tmp_path / "bin"))


def test_download_is_refused_from_a_remote_session(monkeypatch):
    from plugins._llama_server.api import llama_server as api

    called = []
    monkeypatch.setattr(download, "download", lambda variant="": called.append(variant))
    monkeypatch.setattr(download, "plan", lambda variant="": called.append(variant))
    handler = api.LlamaServer(app=None, thread_lock=None)
    tunnel = types.SimpleNamespace(remote_addr="127.0.0.1", headers={"CF-Connecting-IP": "203.0.113.9"})
    for action in ("download", "download_plan"):
        result = asyncio.run(handler.process({"action": action}, tunnel))
        assert result["ok"] is False and "only possible on this PC" in result["error"]
    assert called == []


def test_autostart_runs_once_and_only_when_enabled(monkeypatch):
    from helpers import plugins
    from plugins._llama_server.extensions.python.job_loop import _40_llama_server as ext

    starts = []

    class FakeSup:
        def status(self):
            return {"state": "stopped", "api_base": ""}

        def start(self, config):
            starts.append(config)

    monkeypatch.setattr(supervisor, "get", lambda: FakeSup())
    monkeypatch.setattr(ext, "_tried", {"done": False})
    monkeypatch.setattr(plugins, "get_plugin_config", lambda name, **k: {"autostart": False})
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert starts == []
    monkeypatch.setattr(plugins, "get_plugin_config", lambda name, **k: {"autostart": True, "model_path": "m.gguf"})
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert len(starts) == 1


def test_settings_become_a_server_config():
    cfg = supervisor.config_from_settings({"model_path": "C:/m/Qwen.gguf", "port": "8091", "gpu_layers": 0,
                                           "extra_args": "--flash-attn on"})
    assert cfg.port == 8091 and cfg.gpu_layers == 0 and cfg.alias == "Qwen"
    cmd = cfg.command()
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[-2:] == ["--flash-attn", "on"]
