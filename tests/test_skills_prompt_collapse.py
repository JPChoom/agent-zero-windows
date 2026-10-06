"""The always-on skills catalog collapses skill families (default: a0-*) into
one line, so they cost few prompt tokens but stay searchable and loadable."""

from __future__ import annotations

from types import SimpleNamespace

from extensions.python.system_prompt import _13_skills_prompt as mod


def _skills(*names):
    return [SimpleNamespace(name=n, description=f"{n} description") for n in names]


def test_a_family_of_three_or_more_becomes_one_line():
    lines: list[str] = []
    rest = mod._collapse_prefixed(
        _skills("a0-create-plugin", "a0-debug-plugin", "a0-review-plugin", "build-skill"), ("a0-",), lines
    )
    assert [s.name for s in rest] == ["build-skill"]
    assert len(lines) == 1 and "a0-* (3 skills" in lines[0]
    assert "a0-create-plugin" in lines[0] and "description" not in lines[0]


def test_small_families_and_other_prefixes_are_left_alone():
    lines: list[str] = []
    skills = _skills("a0-one", "a0-two", "other")
    assert mod._collapse_prefixed(skills, ("a0-",), lines) == skills
    assert lines == []


def test_no_prefixes_means_no_collapsing():
    lines: list[str] = []
    skills = _skills("a0-a", "a0-b", "a0-c")
    assert mod._collapse_prefixed(skills, (), lines) == skills


def test_config_can_override_the_prefixes(monkeypatch):
    from helpers import plugins

    monkeypatch.setattr(plugins, "get_plugin_config", lambda name, agent=None, **kw: {"catalog_collapse_prefixes": ["x-"]})
    assert mod._collapse_prefixes(object()) == ("x-",)
    monkeypatch.setattr(plugins, "get_plugin_config", lambda name, agent=None, **kw: {"catalog_collapse_prefixes": "oops"})
    assert mod._collapse_prefixes(object()) == mod.DEFAULT_COLLAPSE_PREFIXES
    monkeypatch.setattr(plugins, "get_plugin_config", lambda name, agent=None, **kw: {})
    assert mod._collapse_prefixes(object()) == mod.DEFAULT_COLLAPSE_PREFIXES
