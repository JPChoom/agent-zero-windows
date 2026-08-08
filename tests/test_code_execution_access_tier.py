"""Tests for tiered filesystem access: helpers/path_containment.py's
resolve_with_tier(), _code_execution's access_tier config resolution, and
resolve_session_cwd()'s tier-aware behavior.
"""

from pathlib import Path

import pytest

from helpers import path_containment
from plugins._code_execution.tools import code_execution_tool as cet


# ------------------------------------------------------------------
# path_containment.resolve_with_tier
# ------------------------------------------------------------------

def test_workdir_only_ignores_roots_outside_default(tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(path_containment.PathNotAllowedError):
        path_containment.resolve_with_tier(
            str(outside), "workdir_only", [str(workdir)], default_root=str(workdir)
        )


def test_workdir_only_allows_path_inside_default(tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    resolved = path_containment.resolve_with_tier(
        "sub/file.txt", "workdir_only", [str(workdir)], default_root=str(workdir)
    )

    assert resolved == str(workdir / "sub" / "file.txt")


def test_allowlist_matches_resolve_within_roots_behavior(tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    external = tmp_path / "external"
    external.mkdir()

    resolved = path_containment.resolve_with_tier(
        str(external / "x.txt"), "allowlist", [str(workdir), str(external)], default_root=str(workdir)
    )

    assert resolved == str(external / "x.txt")

    with pytest.raises(path_containment.PathNotAllowedError):
        path_containment.resolve_with_tier(
            str(tmp_path / "elsewhere" / "x.txt"),
            "allowlist",
            [str(workdir), str(external)],
            default_root=str(workdir),
        )


def test_unrestricted_accepts_any_absolute_path(tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    anywhere = tmp_path / "anywhere" / "deep"
    anywhere.mkdir(parents=True)

    resolved = path_containment.resolve_with_tier(
        str(anywhere / "x.txt"), "unrestricted", [str(workdir)], default_root=str(workdir)
    )

    assert resolved == str(anywhere / "x.txt")


def test_unrestricted_resolves_relative_against_default_root(tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    resolved = path_containment.resolve_with_tier(
        "sub/file.txt", "unrestricted", [str(workdir)], default_root=str(workdir)
    )

    assert resolved == str(workdir / "sub" / "file.txt")


def test_unrestricted_still_resolves_symlinks(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    resolved = path_containment.resolve_with_tier(
        str(link / "x.txt"), "unrestricted", [], default_root=str(tmp_path)
    )

    assert resolved == str((real / "x.txt").resolve(strict=False))


# ------------------------------------------------------------------
# code_execution_tool: access_tier config resolution
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("workdir_only", "workdir_only"),
        ("allowlist", "allowlist"),
        ("unrestricted", "unrestricted"),
        ("", "workdir_only"),
        ("bogus", "workdir_only"),
        ("UNRESTRICTED", "unrestricted"),
    ],
)
def test_resolve_access_tier_falls_back_to_strictest(raw, expected):
    assert cet._resolve_access_tier(raw) == expected


def test_get_config_includes_access_tier(monkeypatch):
    monkeypatch.setattr(
        cet.plugins, "get_plugin_config", lambda *a, **k: {"access_tier": "allowlist"}
    )

    cfg = cet._get_config(agent=None)

    assert cfg["access_tier"] == "allowlist"


def test_get_config_defaults_access_tier_when_unset(monkeypatch):
    monkeypatch.setattr(cet.plugins, "get_plugin_config", lambda *a, **k: {})

    cfg = cet._get_config(agent=None)

    assert cfg["access_tier"] == "workdir_only"


# ------------------------------------------------------------------
# CodeExecution.resolve_session_cwd - tier-aware
# ------------------------------------------------------------------

def _make_tool():
    # Bypass Tool.__init__ (needs a real Agent) - resolve_session_cwd only
    # touches self._requested_cwd and self.ensure_cwd(), neither of which
    # needs the rest of the tool's state for this test.
    return object.__new__(cet.CodeExecution)


@pytest.fixture(autouse=True)
def _stub_make_dir(monkeypatch, tmp_path):
    # resolve_session_cwd calls runtime.call_development_function(make_dir, ...)
    # after resolving - stub both out so tests never touch the real filesystem
    # or the RFC/dev-container path.
    async def _fake_call_development_function(func, *args, **kwargs):
        return None

    monkeypatch.setattr(cet.runtime, "call_development_function", _fake_call_development_function)


def _set_workdir(monkeypatch, workdir: Path):
    monkeypatch.setattr(
        cet.settings, "get_settings", lambda: {"workdir_path": str(workdir)}
    )


@pytest.mark.asyncio
async def test_resolve_session_cwd_workdir_only_rejects_external(monkeypatch, tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    _set_workdir(monkeypatch, workdir)

    tool = _make_tool()
    tool._requested_cwd = str(external)

    with pytest.raises(path_containment.PathNotAllowedError):
        await tool.resolve_session_cwd({"access_tier": "workdir_only", "allowed_external_roots": [str(external)]})


@pytest.mark.asyncio
async def test_resolve_session_cwd_allowlist_allows_configured_external(monkeypatch, tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    _set_workdir(monkeypatch, workdir)

    tool = _make_tool()
    tool._requested_cwd = str(external)

    resolved = await tool.resolve_session_cwd(
        {"access_tier": "allowlist", "allowed_external_roots": [str(external)]}
    )

    assert resolved == str(external)


@pytest.mark.asyncio
async def test_resolve_session_cwd_unrestricted_allows_anywhere(monkeypatch, tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    anywhere = tmp_path / "anywhere"
    anywhere.mkdir()
    _set_workdir(monkeypatch, workdir)

    tool = _make_tool()
    tool._requested_cwd = str(anywhere)

    resolved = await tool.resolve_session_cwd(
        {"access_tier": "unrestricted", "allowed_external_roots": []}
    )

    assert resolved == str(anywhere)


@pytest.mark.asyncio
async def test_resolve_session_cwd_workdir_only_still_allows_workdir_itself(monkeypatch, tmp_path: Path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    _set_workdir(monkeypatch, workdir)

    tool = _make_tool()
    tool._requested_cwd = "sub/project"

    resolved = await tool.resolve_session_cwd(
        {"access_tier": "workdir_only", "allowed_external_roots": []}
    )

    assert resolved == str(workdir / "sub" / "project")
