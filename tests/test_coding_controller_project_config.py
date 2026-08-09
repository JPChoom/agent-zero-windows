"""Tests for Phase G's per-project coding.yaml convenience loader
(config.py's get_config_for_root/load_coding_yaml) and its wiring into
the completion gate extension and the manual coding_gate tool.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins._coding_controller.helpers import config
from plugins._coding_controller.tools.coding_gate import CodingGate


# ------------------------------------------------------------------
# load_coding_yaml
# ------------------------------------------------------------------

def test_load_coding_yaml_returns_empty_when_no_file(tmp_path: Path):
    assert config.load_coding_yaml(str(tmp_path)) == {}


def test_load_coding_yaml_parses_valid_file(tmp_path: Path):
    (tmp_path / "coding.yaml").write_text(
        "npm_test_args: \"test:ci\"\ndotnet_restore_first: false\n", encoding="utf-8"
    )

    result = config.load_coding_yaml(str(tmp_path))

    assert result == {"npm_test_args": "test:ci", "dotnet_restore_first": False}


def test_load_coding_yaml_degrades_gracefully_on_malformed_yaml(tmp_path: Path):
    (tmp_path / "coding.yaml").write_text("not: valid: yaml: [unclosed", encoding="utf-8")

    assert config.load_coding_yaml(str(tmp_path)) == {}


def test_load_coding_yaml_degrades_gracefully_on_non_dict_yaml(tmp_path: Path):
    (tmp_path / "coding.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

    assert config.load_coding_yaml(str(tmp_path)) == {}


# ------------------------------------------------------------------
# get_config_for_root
# ------------------------------------------------------------------

def test_get_config_for_root_returns_base_config_when_no_coding_yaml(tmp_path: Path, monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})

    cfg = config.get_config_for_root(None, str(tmp_path))

    assert cfg == config.get_config(None)


def test_get_config_for_root_overrides_build_command_fields(tmp_path: Path, monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})
    (tmp_path / "coding.yaml").write_text(
        "npm_test_args: \"test:ci\"\ncommand_timeout_seconds: 900\n", encoding="utf-8"
    )

    cfg = config.get_config_for_root(None, str(tmp_path))

    assert cfg["npm_test_args"] == "test:ci"
    assert cfg["command_timeout_seconds"] == 900


def test_get_config_for_root_ignores_malformed_int_override(tmp_path: Path, monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})
    (tmp_path / "coding.yaml").write_text("command_timeout_seconds: \"not a number\"\n", encoding="utf-8")

    cfg = config.get_config_for_root(None, str(tmp_path))

    assert cfg["command_timeout_seconds"] == config.get_config(None)["command_timeout_seconds"]


def test_get_config_for_root_coerces_bool_fields(tmp_path: Path, monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})
    (tmp_path / "coding.yaml").write_text("powershell_lint_enabled: \"false\"\n", encoding="utf-8")

    cfg = config.get_config_for_root(None, str(tmp_path))

    assert cfg["powershell_lint_enabled"] is False


def test_get_config_for_root_cannot_override_enforcement_toggles(tmp_path: Path, monkeypatch):
    """coding.yaml is scoped to build-command fields only - enforcement
    toggles stay Settings-UI-only (see config.py's module docstring for
    why: they're evaluated before any project root is known)."""
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})
    (tmp_path / "coding.yaml").write_text(
        "enforce_completion_gate: true\n"
        "max_repair_attempts: 99\n"
        "enable_independent_review: true\n"
        "enable_diagnostician: true\n"
        "review_blocking_severity: low\n",
        encoding="utf-8",
    )

    cfg = config.get_config_for_root(None, str(tmp_path))

    base = config.get_config(None)
    assert cfg["enforce_completion_gate"] == base["enforce_completion_gate"]
    assert cfg["max_repair_attempts"] == base["max_repair_attempts"]
    assert cfg["enable_independent_review"] == base["enable_independent_review"]
    assert cfg["enable_diagnostician"] == base["enable_diagnostician"]
    assert cfg["review_blocking_severity"] == base["review_blocking_severity"]


def test_get_config_for_root_ignores_unknown_keys(tmp_path: Path, monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})
    (tmp_path / "coding.yaml").write_text("some_made_up_key: 123\n", encoding="utf-8")

    cfg = config.get_config_for_root(None, str(tmp_path))

    assert "some_made_up_key" not in cfg


def test_get_config_for_root_layers_on_top_of_settings_ui_config(tmp_path: Path, monkeypatch):
    """Settings-UI-configured values (from get_plugin_config) still apply
    for fields coding.yaml doesn't mention."""
    import helpers.plugins as plugins_module

    monkeypatch.setattr(
        plugins_module,
        "get_plugin_config",
        lambda plugin_name, agent=None: {"npm_test_args": "from-settings-ui", "go_test_args": "from-settings-ui"},
    )
    (tmp_path / "coding.yaml").write_text("npm_test_args: \"from-coding-yaml\"\n", encoding="utf-8")

    cfg = config.get_config_for_root(None, str(tmp_path))

    assert cfg["npm_test_args"] == "from-coding-yaml"  # coding.yaml wins
    assert cfg["go_test_args"] == "from-settings-ui"  # untouched field passes through


# ------------------------------------------------------------------
# coding_gate.py tool wiring - explicit path check picks up coding.yaml
# ------------------------------------------------------------------

class _FakeAgent:
    def __init__(self):
        self.data = {}


@pytest.mark.asyncio
async def test_coding_gate_explicit_path_check_applies_coding_yaml(tmp_path: Path, monkeypatch):
    import helpers.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "coding.yaml").write_text("npm_test_args: \"test:ci\"\n", encoding="utf-8")

    captured = {}

    async def fake_run_gate_for_root(root, kind, cfg):
        captured["cfg"] = cfg
        return {"passed": True, "skipped": False, "reason": "", "stages": [], "root": root, "kind": kind}

    from plugins._coding_controller.helpers import gate_controller
    monkeypatch.setattr(gate_controller, "run_gate_for_root", fake_run_gate_for_root)

    tool = CodingGate(
        agent=_FakeAgent(), name="coding_gate", method=None,
        args={"action": "check", "path": str(tmp_path)}, message="", loop_data=None,
    )
    await tool.execute()

    assert captured["cfg"]["npm_test_args"] == "test:ci"


@pytest.mark.asyncio
async def test_coding_gate_dirty_roots_check_applies_coding_yaml(tmp_path: Path, monkeypatch):
    import helpers.plugins as plugins_module
    from plugins._coding_controller.helpers import gate_controller, session_state

    monkeypatch.setattr(plugins_module, "get_plugin_config", lambda plugin_name, agent=None: {})
    (tmp_path / "coding.yaml").write_text("npm_test_args: \"test:ci\"\n", encoding="utf-8")

    captured = {}

    async def fake_run_gate_for_root(root, kind, cfg):
        captured["cfg"] = cfg
        return {"passed": True, "skipped": False, "reason": "", "stages": [], "root": root, "kind": kind}

    monkeypatch.setattr(gate_controller, "run_gate_for_root", fake_run_gate_for_root)

    agent = _FakeAgent()
    agent.data[session_state.DIRTY_ROOTS_KEY] = {str(tmp_path): "npm"}

    tool = CodingGate(agent=agent, name="coding_gate", method=None, args={"action": "check"}, message="", loop_data=None)
    await tool.execute()

    assert captured["cfg"]["npm_test_args"] == "test:ci"
