"""Shared test isolation.

Permission modes are per chat and start at the `permissions_default_mode`
setting - "manual" by default, which *asks* before any edit or command.
Tests that drive tools through the real tool_execute_before chain would
then wait (up to the approval timeout) for a click no test makes. Unless a
test is about permissions itself (those patch mode_state explicitly and win
over this fixture), run with the pre-plugin "auto" behavior, and never read
the developer's own usr/settings.json default.
"""

import pytest


@pytest.fixture(autouse=True)
def _permissions_default_mode_auto_for_tests(monkeypatch):
    try:
        from plugins._permissions.helpers import mode_state
    except Exception:
        yield
        return
    monkeypatch.setattr(mode_state, "default_mode", lambda: "auto")
    mode_state.clear_all()
    yield
    mode_state.clear_all()


# -- Platform markers ------------------------------------------------------
#
# This fork runs natively on Windows; upstream's suite also covers Docker /
# Linux behavior. Tests that only make sense there are marked, not deleted,
# so they still run on Linux CI and the skip reason stays visible:
#   @pytest.mark.posix_only       POSIX-only APIs (permission bits, /tmp, geteuid)
#   @pytest.mark.linux_only       Linux tooling (X11/xpra/apt, Linux Tailscale binaries)
#   @pytest.mark.docker_layout    assumes the Docker /a0 path layout
#   @pytest.mark.needs_symlinks   creates symlinks (Windows needs Developer Mode/admin)

import os
import sys
import tempfile


def _symlinks_supported() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "t")
        open(target, "w").close()
        try:
            os.symlink(target, os.path.join(tmp, "l"))
            return True
        except (OSError, NotImplementedError):
            return False


_PLATFORM_SKIPS = {
    "posix_only": (os.name == "nt", "POSIX-only behavior; not applicable on Windows"),
    "linux_only": (not sys.platform.startswith("linux"), "Linux-only tooling"),
    "docker_layout": (os.name == "nt", "assumes the Docker /a0 path layout"),
}


def pytest_configure(config):
    config.addinivalue_line("markers", "posix_only: POSIX-only behavior")
    config.addinivalue_line("markers", "linux_only: Linux-only tooling")
    config.addinivalue_line("markers", "docker_layout: assumes the Docker /a0 path layout")
    config.addinivalue_line("markers", "needs_symlinks: creates symlinks")


def pytest_collection_modifyitems(config, items):
    symlinks = None
    for item in items:
        for name, (skip, reason) in _PLATFORM_SKIPS.items():
            if skip and item.get_closest_marker(name):
                item.add_marker(pytest.mark.skip(reason=reason))
        if item.get_closest_marker("needs_symlinks"):
            if symlinks is None:
                symlinks = _symlinks_supported()
            if not symlinks:
                item.add_marker(
                    pytest.mark.skip(reason="cannot create symlinks here (Windows: enable Developer Mode)")
                )
