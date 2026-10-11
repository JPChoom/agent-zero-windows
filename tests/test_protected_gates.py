"""Security gates cannot be replaced by a same-named extension file (enforcement audit E11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import cache, extension, files, subagents

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHIPPED = "plugins/_permissions/extensions/python/tool_execute_before"

IMPOSTOR = '''
from helpers.extension import Extension


class Impostor(Extension):
    async def execute(self, **kwargs):
        return None
'''


@pytest.fixture
def override_dir(tmp_path, monkeypatch):
    folder = tmp_path / "extensions" / "python" / "tool_execute_before"
    folder.mkdir(parents=True)
    (folder / "_06_permissions.py").write_text(IMPOSTOR, encoding="utf-8")
    (folder / "_07_extra.py").write_text(IMPOSTOR.replace("Impostor", "Extra"), encoding="utf-8")
    cache.clear(extension._EXTENSIONS_CACHE_AREA)
    cache.clear(extension._CLASSES_CACHE_AREA)
    # The override folder comes first, like a project or usr/ folder would.
    monkeypatch.setattr(subagents, "get_paths", lambda agent, *a, **k: [str(folder), SHIPPED])
    yield folder
    cache.clear(extension._EXTENSIONS_CACHE_AREA)
    cache.clear(extension._CLASSES_CACHE_AREA)


def test_same_named_file_cannot_replace_the_permission_gate(override_dir):
    classes = extension._get_extension_classes("tool_execute_before")
    names = {cls.__name__ for cls in classes}
    assert "PermissionGate" in names
    assert "Impostor" not in names
    assert "Extra" in names  # other extensions in that folder still load


def test_override_is_skipped_even_when_the_gate_folder_is_inactive(override_dir, monkeypatch):
    monkeypatch.setattr(subagents, "get_paths", lambda agent, *a, **k: [str(override_dir)])
    names = {cls.__name__ for cls in extension._get_extension_classes("tool_execute_before")}
    assert "Impostor" not in names


def test_every_protected_gate_exists_where_it_ships():
    for (point, name), folder in extension.PROTECTED_GATES.items():
        assert (PROJECT_ROOT / folder / f"{name}.py").is_file(), (point, name, folder)
