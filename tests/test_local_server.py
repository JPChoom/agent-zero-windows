"""The local model server around the supervisor (Settings > Models > Local
model server): download safety, the API's local-only download, autostart,
presets, model discovery, the MTP check and migration from the former
_llama_server plugin. No network and no GPU: release data, archives and GGUF
headers are built in the test."""

from __future__ import annotations

import asyncio
import io
import types
import zipfile

import pytest

from helpers import llama_download as download
from helpers import llama_server as supervisor
from helpers import local_server

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
    from api import llama_server as api

    called = []
    monkeypatch.setattr(download, "download", lambda variant="": called.append(variant))
    monkeypatch.setattr(download, "plan", lambda variant="": called.append(variant))
    handler = api.LlamaServer(app=None, thread_lock=None)
    tunnel = types.SimpleNamespace(remote_addr="127.0.0.1", headers={"CF-Connecting-IP": "203.0.113.9"})
    for action in ("download", "download_plan"):
        result = asyncio.run(handler.process({"action": action}, tunnel))
        assert result["ok"] is False and "only possible on this PC" in result["error"]
    assert called == []


def _model_cfg(**local):
    return {"chat_model": {"provider": "lm_studio"}, "local_server": {**local_server.DEFAULTS, **local}}


class _FakeSup:
    def __init__(self, state="stopped", identity=""):
        self.state, self.identity, self.starts, self.stops = state, identity, [], 0

    def status(self):
        return {"state": self.state, "api_base": ""}

    def running_identity(self):
        return self.identity

    def start(self, config):
        self.starts.append(config)
        self.state = "running"

    def stop(self):
        self.stops += 1


def test_autostart_runs_once_and_only_when_enabled(monkeypatch, tmp_path):
    from extensions.python.job_loop import _40_llama_server as ext

    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    sup = _FakeSup()
    monkeypatch.setattr(supervisor, "get", lambda: sup)
    monkeypatch.setattr(ext, "_tried", {"done": False})
    monkeypatch.setattr(local_server, "model_config", lambda: _model_cfg(autostart=False, model_path=str(model)))
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert sup.starts == []
    monkeypatch.setattr(local_server, "model_config", lambda: _model_cfg(autostart=True, model_path=str(model)))
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    sup.state = "stopped"  # stopped by hand afterwards: not started again
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert len(sup.starts) == 1


def test_saved_changes_restart_a_running_server_but_never_mid_turn(monkeypatch, tmp_path):
    from extensions.python.job_loop import _40_llama_server as ext
    from helpers import model_concurrency

    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setattr(local_server, "model_config", lambda: _model_cfg(model_path=str(model), preset="balanced"))
    wanted = local_server.server_config().identity()

    sup = _FakeSup(state="running", identity="old-settings")
    monkeypatch.setattr(supervisor, "get", lambda: sup)
    monkeypatch.setattr(model_concurrency, "foreground_busy", lambda: True)
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert sup.starts == []  # a turn is running: wait

    # no model call is waiting, but a chat is mid-turn (a tool is running)
    monkeypatch.setattr(model_concurrency, "foreground_busy", lambda: False)
    from agent import AgentContext

    class _Ctx:
        def __init__(self, running):
            self._running = running

        def is_running(self):
            return self._running

    monkeypatch.setattr(AgentContext, "all", staticmethod(lambda: [_Ctx(False), _Ctx(True)]))
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert sup.starts == []  # waits for the turn to finish

    monkeypatch.setattr(AgentContext, "all", staticmethod(lambda: [_Ctx(False)]))
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert sup.stops == 1 and sup.starts[0].identity() == wanted

    same = _FakeSup(state="running", identity=wanted)
    monkeypatch.setattr(supervisor, "get", lambda: same)
    asyncio.run(ext.LlamaServerAutostart(agent=None).execute())
    assert same.starts == [] and same.stops == 0


def test_settings_become_a_server_config():
    cfg = supervisor.config_from_settings({"model_path": "C:/m/Qwen.gguf", "port": "8091", "gpu_layers": 0,
                                           "extra_args": "--flash-attn on"})
    assert cfg.port == 8091 and cfg.gpu_layers == 0 and cfg.alias == "Qwen"
    cmd = cfg.command()
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[-2:] == ["--flash-attn", "on"]


# ------------------------------------------------------------ presets, MTP, wiring

import struct


def _gguf(path, nextn=None, arch="qwen35"):
    """A minimal GGUF header: architecture, a string array (like the
    tokenizer vocab, which the reader must skip) and optionally nextn layers."""
    def s(text):
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw

    kvs = [s("general.architecture") + struct.pack("<I", 8) + s(arch),
           s("tokenizer.ggml.tokens") + struct.pack("<IIQ", 9, 8, 3) + s("a") + s("bb") + s("ccc"),
           s(f"{arch}.block_count") + struct.pack("<I", 4) + struct.pack("<I", 64)]
    if nextn is not None:
        kvs.append(s(f"{arch}.nextn_predict_layers") + struct.pack("<I", 4) + struct.pack("<I", nextn))
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, len(kvs)) + b"".join(kvs))
    return str(path)


def test_mtp_layer_is_read_from_the_gguf_header(tmp_path):
    assert local_server.has_mtp(_gguf(tmp_path / "with.gguf", nextn=1))
    assert not local_server.has_mtp(_gguf(tmp_path / "zero.gguf", nextn=0))
    assert not local_server.has_mtp(_gguf(tmp_path / "none.gguf"))
    (tmp_path / "junk.gguf").write_bytes(b"not a gguf")
    assert not local_server.has_mtp(str(tmp_path / "junk.gguf"))
    assert not local_server.has_mtp(str(tmp_path / "missing.gguf"))


def test_presets(tmp_path):
    mtp = _gguf(tmp_path / "mtp.gguf", nextn=1)
    plain = _gguf(tmp_path / "plain.gguf")
    fast = local_server.FAST_FLAGS
    assert local_server.preset_args("coding", mtp) == fast + local_server.MTP_FLAGS
    assert local_server.preset_args("coding", plain) == fast  # no MTP layer, no drafting
    assert local_server.preset_args("balanced", mtp) == fast
    assert "q4_0" in local_server.preset_args("low_memory", mtp)
    assert local_server.preset_args("custom", mtp, "--temp 0.5") == ["--temp", "0.5"]
    with pytest.raises(supervisor.SupervisorError):
        local_server.preset_args("custom", mtp, "--host 0.0.0.0")


def test_context_follows_the_main_slot_while_main_uses_this_server(tmp_path):
    model = _gguf(tmp_path / "Qwen.gguf", nextn=1)
    cfg = {"chat_model": {"provider": "llama_cpp", "api_base": "http://127.0.0.1:8090/v1", "ctx_length": 49152},
           "local_server": {"model_path": model, "context_size": 8192}}
    assert local_server.server_config(cfg).context_size == 49152
    cfg["chat_model"]["api_base"] = ""  # the provider default is this server too
    assert local_server.server_config(cfg).context_size == 49152
    cfg["chat_model"] = {"provider": "lm_studio", "ctx_length": 49152}
    assert local_server.server_config(cfg).context_size == 8192


def test_coding_preset_builds_the_benchmarked_command(tmp_path):
    model = _gguf(tmp_path / "Qwen3.8-27B-Uncensored-Q4_K_M.gguf", nextn=1)
    cfg = {"chat_model": {"provider": "llama_cpp", "ctx_length": 49152},
           "local_server": {"model_path": model, "preset": "coding"}}
    cmd = local_server.server_config(cfg).command()
    tail = " ".join(cmd[cmd.index("-c"):])
    assert tail == ("-c 49152 -ngl 99 -np 1 -fa on -ctk q8_0 -ctv q8_0 --jinja --cache-reuse 256 "
                    "--spec-type draft-mtp --spec-draft-n-max 6")


def test_vision_adds_the_models_own_projector(tmp_path):
    model = _gguf(tmp_path / "Qwen.gguf")
    cfg = {"local_server": {"model_path": model, "vision": True, "preset": "balanced"}}
    assert "--mmproj" not in local_server.server_config(cfg).command()  # none next to it
    projector = tmp_path / "mmproj-Qwen-F16.gguf"
    projector.write_bytes(b"GGUF")
    cmd = local_server.server_config(cfg).command()
    assert cmd[cmd.index("--mmproj") + 1] == str(projector)


def test_projector_is_matched_to_the_model_by_name(tmp_path):
    model = tmp_path / "Qwen3.8-27B-Uncensored-Q4_K_M.gguf"
    model.write_bytes(b"x")
    for name in ("mmproj-Gemma3-4B-F16.gguf", "mmproj-Qwen3.8-27B-Uncensored-F16.gguf", "mmproj-Aaa-F16.gguf"):
        (tmp_path / name).write_bytes(b"x")
    assert local_server.mmproj_for(str(model)).endswith("mmproj-Qwen3.8-27B-Uncensored-F16.gguf")


def test_several_projectors_and_no_match_means_no_guess(tmp_path):
    model = tmp_path / "Llama-3-8B-Q4_K_M.gguf"
    model.write_bytes(b"x")
    for name in ("mmproj-Gemma3-4B-F16.gguf", "mmproj-Qwen-VL-F16.gguf"):
        (tmp_path / name).write_bytes(b"x")
    assert local_server.mmproj_for(str(model)) == ""
    only = tmp_path / "sub"
    only.mkdir()
    (only / "m.gguf").write_bytes(b"x")
    (only / "mmproj-whatever-F16.gguf").write_bytes(b"x")
    assert local_server.mmproj_for(str(only / "m.gguf")).endswith("mmproj-whatever-F16.gguf")  # a single file is taken


def test_a_named_projector_overrides_the_guess(tmp_path):
    model = _gguf(tmp_path / "Qwen.gguf")
    mine = tmp_path / "elsewhere.gguf"
    mine.write_bytes(b"x")
    (tmp_path / "mmproj-Qwen-F16.gguf").write_bytes(b"x")
    cfg = {"local_server": {"model_path": model, "vision": True, "preset": "balanced", "mmproj_path": str(mine)}}
    cmd = local_server.server_config(cfg).command()
    assert cmd[cmd.index("--mmproj") + 1] == str(mine)
    cfg["local_server"]["mmproj_path"] = str(tmp_path / "missing.gguf")  # not a file: back to the name match
    cmd = local_server.server_config(cfg).command()
    assert cmd[cmd.index("--mmproj") + 1].endswith("mmproj-Qwen-F16.gguf")


def test_model_list_skips_projectors_and_embeddings(tmp_path, monkeypatch):
    own, lms = tmp_path / "own", tmp_path / "lms" / "pub" / "repo"
    own.mkdir(); lms.mkdir(parents=True)
    for name in ("Chat-Q4_K_M.gguf", "mmproj-Chat-F16.gguf", "bge-m3-Q8_0.gguf", "Qwen3-Embedding-4B.gguf"):
        (lms / name).write_bytes(b"x")
    (own / "Mine.gguf").write_bytes(b"x")
    monkeypatch.setattr(local_server, "own_models_dir", lambda: str(own))
    monkeypatch.setattr(local_server, "lm_studio_models_dir", lambda: str(tmp_path / "lms"))
    models = local_server.list_models({"model_folders": []})
    assert [(m["folder"], m["alias"], m["has_mmproj"]) for m in models] == [
        ("Agent Zero", "Mine", False), ("LM Studio", "Chat-Q4_K_M", True)]


@pytest.mark.parametrize("old_args,preset,extra", [
    ("", "balanced", ""),
    ("-fa on -ctk q8_0 -ctv q8_0 --jinja --cache-reuse 256 --spec-type draft-mtp --spec-draft-n-max 6", "coding", ""),
    ("-fa on -ctk q8_0 -ctv q8_0 --jinja --cache-reuse 256", "balanced", ""),
    ("--temp 0.3", "custom", "--temp 0.3"),
])
def test_former_plugin_settings_migrate(tmp_path, monkeypatch, old_args, preset, extra):
    import json

    old = tmp_path / "config.json"
    old.write_text(json.dumps({"autostart": True, "model_path": "C:/m/x.gguf", "port": 8090, "context_size": 49152,
                               "gpu_layers": 99, "extra_args": old_args}), encoding="utf-8")
    monkeypatch.setattr(local_server, "old_plugin_config_path", lambda: str(old))
    s = local_server.migrated_settings()
    assert s["autostart"] is True and s["model_path"] == "C:/m/x.gguf" and s["context_size"] == 49152
    assert s["preset"] == preset and s["extra_args"] == extra


def test_no_former_plugin_means_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(local_server, "old_plugin_config_path", lambda: str(tmp_path / "missing.json"))
    assert local_server.migrated_settings() == local_server.DEFAULTS


def test_model_config_gains_local_server_from_the_migration(monkeypatch):
    from plugins._model_config import hooks

    monkeypatch.setattr(local_server, "migrated_settings", lambda: {"marker": True})
    cfg = hooks.get_plugin_config(default={"chat_model": {}, "vision_model": {}, "single_model_mode": False, "sampling": {}})
    assert cfg["local_server"] == {"marker": True}
    saved = {"local_server": {"preset": "custom"}, "vision_model": {}, "single_model_mode": False, "sampling": {}}
    assert hooks.get_plugin_config(default=saved)["local_server"] == {"preset": "custom"}


def test_settings_ui_wires_main_and_utility_on_pick():
    from pathlib import Path

    ui = Path("plugins/_model_config/webui/local-server.html").read_text(encoding="utf-8")
    assert "this.alsoUtility ? ['chat_model', 'utility_model'] : ['chat_model']" in ui  # Utility is optional
    assert "alsoUtility: true" in ui  # on by default, as before
    assert "provider: 'llama_cpp', name: m.alias, api_base: this.base()" in ui
    config_html = Path("plugins/_model_config/webui/config.html").read_text(encoding="utf-8")
    assert "/plugins/_model_config/webui/local-server.html" in config_html


def test_former_plugin_is_gone():
    from pathlib import Path

    assert not Path("plugins/_llama_server").exists()
