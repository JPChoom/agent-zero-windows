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
