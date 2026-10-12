"""The agent is told about vision_load whenever it can get image content,
either because the Main model sees images or because a vision sidecar model
describes them. With a sidecar and a text-only Main model the tool used to be
left out of the prompt, so the agent never called it and the sidecar was never
used (the agent probed the terminal for image tools instead)."""

from __future__ import annotations

import asyncio
import types

import pytest

from extensions.python.system_prompt import _11_tools_prompt as tools_prompt
from plugins._model_config.helpers import model_config

VISION_HEADING = "### vision_load"
SIDECAR_NOTE = "You cannot see images yourself"


class _Agent:
    data: dict = {}

    def get_data(self, key):
        return self.data.get(key)

    def read_prompt(self, name, **kwargs):
        if name == "agent.system.tools_vision.md":
            return "## multimodal vision tools\n\n### vision_load\nload images"
        return "TOOLS"


@pytest.fixture
def prompt(monkeypatch):
    monkeypatch.setattr(tools_prompt.subagents, "get_paths", lambda agent, *a, **k: [])
    monkeypatch.setattr(tools_prompt.files, "get_unique_filenames_in_dirs", lambda dirs, pattern: [])

    def build(main_vision: bool, sidecar: bool, single_model: bool = False) -> str:
        monkeypatch.setattr(model_config, "get_chat_model_config", lambda agent=None: {"vision": main_vision})
        monkeypatch.setattr(model_config, "get_config", lambda agent=None, **k: {
            "single_model_mode": single_model,
            "vision_model": {"provider": "lm_studio", "name": "smolvlm-500m-instruct"} if sidecar else {"provider": "lm_studio", "name": ""},
        })
        return asyncio.run(tools_prompt.build_prompt(_Agent()))

    return build


def test_text_only_main_model_with_a_sidecar_gets_vision_load(prompt):
    text = prompt(main_vision=False, sidecar=True)
    assert VISION_HEADING in text and SIDECAR_NOTE in text


def test_main_model_with_vision_gets_vision_load_without_the_sidecar_note(prompt):
    text = prompt(main_vision=True, sidecar=True)
    assert VISION_HEADING in text and SIDECAR_NOTE not in text


def test_no_vision_and_no_sidecar_gets_no_vision_tool(prompt):
    text = prompt(main_vision=False, sidecar=False)
    assert VISION_HEADING not in text and SIDECAR_NOTE not in text


def test_single_model_mode_ignores_the_sidecar(prompt):
    text = prompt(main_vision=False, sidecar=True, single_model=True)
    assert VISION_HEADING not in text
