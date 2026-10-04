"""Newly installed third-party plugins are inert until the user enables
them: not enabled (even with always_enabled), hooks.py never imported,
install hook deferred to the first global enable."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import cache, plugins


@pytest.fixture
def pending_plugin(tmp_path, monkeypatch):
    pdir = tmp_path / "usr" / "plugins" / "evil"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text("name: evil\nalways_enabled: true\n")
    ran = tmp_path / "hook_ran.txt"
    (pdir / "hooks.py").write_text(
        "from pathlib import Path\n"
        f"Path(r'{tmp_path / 'imported.txt'}').write_text('x')\n"
        "def install():\n"
        f"    Path(r'{ran}').write_text('installed')\n"
    )
    (pdir / plugins.REVIEW_PENDING_FILE_NAME).write_text("")

    monkeypatch.setattr(plugins, "find_plugin_dir", lambda name: str(pdir) if name == "evil" else None)
    monkeypatch.setattr(
        plugins, "get_plugin_meta",
        lambda name: plugins.PluginMetadata(name="evil", always_enabled=True) if name == "evil" else None,
    )
    monkeypatch.setattr(
        plugins, "determine_plugin_asset_path",
        lambda name, project, profile, fname: str(pdir / fname),
    )
    monkeypatch.setattr(plugins, "after_plugin_change", lambda *a, **k: None)
    cache.clear(plugins.HOOKS_CACHE_AREA)
    yield pdir, tmp_path
    cache.clear(plugins.HOOKS_CACHE_AREA)


def test_pending_plugin_is_disabled_despite_always_enabled(pending_plugin):
    assert plugins.is_review_pending("evil")
    assert plugins.get_toggle_state("evil") == "disabled"


def test_pending_plugin_hooks_are_never_imported(pending_plugin):
    _, tmp = pending_plugin
    assert plugins.call_plugin_hook("evil", "install", default="skipped") == "skipped"
    assert not (tmp / "imported.txt").exists()
    assert not (tmp / "hook_ran.txt").exists()


def test_project_scope_enable_does_not_lift_review(pending_plugin):
    pdir, tmp = pending_plugin
    plugins.toggle_plugin("evil", True, project_name="proj")
    assert plugins.is_review_pending("evil")
    assert not (tmp / "hook_ran.txt").exists()


def test_global_enable_runs_deferred_install_hook_and_clears_review(pending_plugin):
    pdir, tmp = pending_plugin
    plugins.toggle_plugin("evil", True)
    assert not plugins.is_review_pending("evil")
    assert (tmp / "hook_ran.txt").read_text() == "installed"
    assert (pdir / plugins.ENABLED_FILE_NAME).exists()


def test_installer_marks_review_pending(tmp_path):
    from plugins._plugin_installer.helpers import install

    install.mark_review_pending(str(tmp_path))
    assert (tmp_path / plugins.REVIEW_PENDING_FILE_NAME).exists()
