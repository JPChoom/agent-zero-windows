"""Every approval card's buttons are styled by the theme.

The infection-check "Safety check: your decision needed" card shipped with
plain, unstyled Allow / Block buttons because its class (infection-check-
decision-btn) was never added to the theme's list. Any handler that builds
`<something>-decision-btn` buttons must be in that list.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _handler_classes() -> dict[str, str]:
    found = {}
    for path in (ROOT / "plugins").glob("*/extensions/webui/get_message_handler/*.js"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"action-button ([a-z0-9-]+-decision-btn)", text):
            found[match.group(1)] = path.relative_to(ROOT).as_posix()
    return found


def test_there_are_approval_handlers_to_check():
    assert {"permissions-decision-btn", "safety-policy-decision-btn", "infection-check-decision-btn"} <= set(_handler_classes())


def test_every_approval_button_class_is_styled_in_the_theme():
    theme = (ROOT / "webui" / "css" / "theme.css").read_text(encoding="utf-8")
    missing = {cls: where for cls, where in _handler_classes().items() if f".{cls}" not in theme}
    assert missing == {}, f"approval buttons with no theme styling: {missing}"


def test_each_class_gets_the_full_set_of_states():
    theme = (ROOT / "webui" / "css" / "theme.css").read_text(encoding="utf-8")
    for cls in _handler_classes():
        for state in (".approve-btn", ".approve-btn:first-child", ".deny-btn:hover:not(:disabled)", ":disabled"):
            assert f".{cls}{state}" in theme, f".{cls}{state} is not styled"
        assert f".{cls}" in re.search(r"\.step-action-buttons:has\(([^)]*)\)", theme).group(1)
