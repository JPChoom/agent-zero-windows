"""Reads and normalizes _coding_controller's plugin config.

Per-project overrides already work with zero extra code: this plugin's
config goes through helpers/plugins.py's generic get_plugin_config(...,
project_name=...) scoping (find_plugin_asset() resolves a config file
under /projects/<project_name>/... ahead of the plugin-wide default) -
the same mechanism every other plugin's Settings UI "Project" selector
already uses. That covers a user configuring a project through Agent
Zero's own UI.

get_config_for_root() adds a second, narrower mechanism on top: a
coding.yaml file committed directly in the project's own root directory,
for teams who want their build-command config checked into version
control and shared via the repo itself rather than configured per-user
through Settings. It only overrides the gate-command fields (build/test
args, per-adapter enable flags, command timeout) - never
enforce_completion_gate/max_repair_attempts/enable_independent_review/
enable_diagnostician/review_blocking_severity, which stay Settings-UI-
only. Those are evaluated once, before any project root is even known
(see _80_completion_gate.py's early return), so a repo-local file being
able to silently flip them would be a confusing, hard-to-reason-about
surprise; the fields it can override are only ever consulted once a
root's gate is already running.
"""

import os

import yaml as pyyaml

from helpers import plugins, yaml as yaml_helper

_CODING_YAML_FILENAME = "coding.yaml"

# The only keys a project's own coding.yaml is allowed to override - see
# the module docstring for why this excludes the enforcement toggles.
_PROJECT_OVERRIDABLE_KEYS = (
    "command_timeout_seconds",
    "dotnet_restore_first",
    "dotnet_build_args",
    "npm_install_first",
    "npm_test_args",
    "powershell_lint_enabled",
    "python_test_args",
    "go_test_args",
    "rust_build_args",
    "java_maven_test_args",
    "java_gradle_test_args",
)


def get_config(agent) -> dict:
    cfg = plugins.get_plugin_config("_coding_controller", agent=agent) or {}
    return {
        "enforce_completion_gate": _as_bool(cfg.get("enforce_completion_gate", False)),
        "max_repair_attempts": int(cfg.get("max_repair_attempts", 3)),
        "command_timeout_seconds": int(cfg.get("command_timeout_seconds", 300)),
        "dotnet_restore_first": _as_bool(cfg.get("dotnet_restore_first", True)),
        "dotnet_build_args": str(cfg.get("dotnet_build_args", "build --no-restore -nologo")),
        "npm_install_first": _as_bool(cfg.get("npm_install_first", False)),
        "npm_test_args": str(cfg.get("npm_test_args", "test")),
        "powershell_lint_enabled": _as_bool(cfg.get("powershell_lint_enabled", True)),
        "enable_independent_review": _as_bool(cfg.get("enable_independent_review", False)),
        "review_blocking_severity": str(cfg.get("review_blocking_severity", "high")),
        "enable_diagnostician": _as_bool(cfg.get("enable_diagnostician", False)),
        "python_test_args": str(cfg.get("python_test_args", "")),
        "go_test_args": str(cfg.get("go_test_args", "./...")),
        "rust_build_args": str(cfg.get("rust_build_args", "build")),
        "java_maven_test_args": str(cfg.get("java_maven_test_args", "test")),
        "java_gradle_test_args": str(cfg.get("java_gradle_test_args", "test")),
    }


def get_config_for_root(agent, project_root: str) -> dict:
    """get_config() merged with project_root's own coding.yaml, if
    present - the repo-local file wins for the keys it sets."""
    cfg = get_config(agent)
    overrides = load_coding_yaml(project_root)
    if not overrides:
        return cfg

    merged = dict(cfg)
    for key in _PROJECT_OVERRIDABLE_KEYS:
        if key not in overrides:
            continue
        raw = overrides[key]
        current = cfg[key]
        if isinstance(current, bool):
            merged[key] = _as_bool(raw)
        elif isinstance(current, int):
            try:
                merged[key] = int(raw)
            except (TypeError, ValueError):
                pass  # malformed override for this key - keep the base value
        else:
            merged[key] = str(raw)
    return merged


def load_coding_yaml(project_root: str) -> dict:
    """Parses <project_root>/coding.yaml, or returns {} if it doesn't
    exist or fails to parse - a malformed convenience file must degrade
    gracefully, not break the gate for the whole project."""
    path = os.path.join(project_root, _CODING_YAML_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml_helper.loads(f.read())
    except (OSError, pyyaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")
