"""Agent changes to a file open in the Editor wait for the user's review."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins._editor.helpers import markdown_sessions as ms

ROOT = Path(__file__).resolve().parents[1]


class _Store:
    """A document store backed by one real file."""

    EDITOR_TEXT_EXTENSIONS = {"md", "txt", "py"}

    def __init__(self, path: Path):
        self.path = path

    def _doc(self):
        data = self.path.read_bytes()
        return {"file_id": "f1", "path": str(self.path), "basename": self.path.name, "extension": self.path.suffix[1:],
                "sha256": self.sha256_bytes(data), "size": len(data), "last_modified": "2026-11-07"}

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def register_document(self, path, context_id="", policy_checked=False):
        return self._doc()

    def get_document(self, file_id):
        return self._doc()

    def read_text_for_editor(self, doc):
        return self.path.read_text(encoding="utf-8")

    def write_text_document(self, file_id, text):
        self.path.write_text(text, encoding="utf-8")
        return self._doc()

    def item_version(self, doc):
        return doc["sha256"][:12]

    def normalize_path(self, value, context_id=""):
        return Path(value).resolve()

    @staticmethod
    def display_path(path):
        return str(path)


@pytest.fixture
def editor(tmp_path, monkeypatch):
    path = tmp_path / "notes.md"
    path.write_text("line one\nline two\n", encoding="utf-8")
    store = _Store(path)
    monkeypatch.setattr(ms, "document_store", store)
    manager = ms.MarkdownSessionManager()
    session = ms.MarkdownSession(session_id="s1", file_id="f1", sid="", context_id="", extension="md",
                                 path=str(path), title="notes.md", text=path.read_text(encoding="utf-8"))
    ms._set_session_base(session, store._doc())
    manager._sessions["s1"] = session
    return SimpleNamespace(manager=manager, session=session, path=path)


def _agent_writes(editor, text):
    editor.path.write_text(text, encoding="utf-8")
    editor.manager.sync_external_file_mutations([str(editor.path)])


def test_an_agent_change_waits_for_review(editor):
    _agent_writes(editor, "line one\nline 2 by the agent\n")
    state = editor.manager.review_state("s1")
    assert state["pending"] and state["before"] == "line one\nline two\n"
    assert state["text"] == "line one\nline 2 by the agent\n" and not state["conflict"]


def test_rejecting_puts_the_old_text_back_on_disk(editor):
    _agent_writes(editor, "changed by the agent\n")
    result = editor.manager.review_resolve("s1", editor.manager.review_state("s1")["before"])
    assert result["ok"] and editor.path.read_text(encoding="utf-8") == "line one\nline two\n"
    assert not editor.manager.review_state("s1")["pending"]


def test_accepting_keeps_the_agents_file(editor):
    _agent_writes(editor, "changed by the agent\n")
    editor.manager.review_resolve("s1", "changed by the agent\n")
    assert editor.path.read_text(encoding="utf-8") == "changed by the agent\n"
    assert not editor.manager.review_state("s1")["pending"]


def test_a_mix_of_accepted_and_rejected_changes_is_saved(editor):
    _agent_writes(editor, "LINE ONE\nLINE TWO\n")
    editor.manager.review_resolve("s1", "LINE ONE\nline two\n")
    assert editor.path.read_text(encoding="utf-8") == "LINE ONE\nline two\n"


def test_several_agent_changes_are_reviewed_against_the_first_before(editor):
    _agent_writes(editor, "first agent change\n")
    _agent_writes(editor, "second agent change\n")
    state = editor.manager.review_state("s1")
    assert state["before"] == "line one\nline two\n" and state["text"] == "second agent change\n"


def test_unsaved_user_text_is_kept_and_flagged(editor):
    editor.session.text = "the user's unsaved text\n"
    editor.session.dirty = True
    _agent_writes(editor, "the agent's text\n")
    state = editor.manager.review_state("s1")
    assert state["conflict"] and state["before"] == "the user's unsaved text\n"
    assert state["text"] == "the agent's text\n"
    assert editor.session.text == "the user's unsaved text\n" and editor.session.dirty  # still in the editor
    editor.manager.review_resolve("s1", state["before"])  # reject: the user's text wins
    assert editor.path.read_text(encoding="utf-8") == "the user's unsaved text\n"


def test_accepting_over_unsaved_text_keeps_the_agents_version(editor):
    editor.session.text = "the user's unsaved text\n"
    editor.session.dirty = True
    _agent_writes(editor, "the agent's text\n")
    assert editor.manager.review_resolve("s1", "the agent's text\n")["ok"]
    assert editor.path.read_text(encoding="utf-8") == "the agent's text\n" and not editor.session.dirty


def test_a_write_that_changes_nothing_needs_no_review(editor):
    _agent_writes(editor, "line one\nline two\n")
    assert not editor.manager.review_state("s1")["pending"]


def test_the_session_payload_says_a_review_is_waiting(editor):
    _agent_writes(editor, "changed\n")
    assert editor.manager._payload(editor.session, editor.path and _Store(editor.path)._doc())["agent_review"] is True


def test_the_panel_and_store_wire_the_review():
    store = (ROOT / "plugins/_editor/webui/editor-store.js").read_text(encoding="utf-8")
    panel = (ROOT / "plugins/_editor/webui/editor-panel.html").read_text(encoding="utf-8")
    review = (ROOT / "plugins/_editor/webui/editor-review.js").read_text(encoding="utf-8")
    assert '"review_state"' in store and '"review_resolve"' in store
    assert "data-editor-review" in panel and "finishReview('reject')" in panel and "finishReview('accept')" in panel
    assert 'from "/vendor/codemirror/codemirror.bundle.js"' in review and "unifiedMergeView" in review
    bundle = ROOT / "webui/vendor/codemirror/codemirror.bundle.js"
    assert bundle.is_file() and (ROOT / "webui/vendor/codemirror/LICENSE").read_text(encoding="utf-8").startswith("MIT License")
