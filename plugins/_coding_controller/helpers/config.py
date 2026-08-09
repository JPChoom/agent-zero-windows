"""Reads and normalizes _coding_controller's plugin config."""

from helpers import plugins


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
    }


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")
