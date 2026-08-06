from __future__ import annotations

from helpers.skills import normalize_skills_config


def get_plugin_config(default=None, **kwargs):
    return normalize_skills_config(default)


def save_plugin_config(settings=None, **kwargs):
    return normalize_skills_config(settings)
