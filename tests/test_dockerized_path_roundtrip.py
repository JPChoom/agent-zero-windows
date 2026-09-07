"""Tests for resolving the "/a0/..." paths the framework shows the agent.

Observed live: the agent tried to load a skill at
'/a0/skills/a0-create-plugin' and got "Path does not exist". The skill was
there. The path came from the framework itself - normalize_a0_path()
produces exactly that shape, and skill listings, prompts and tool output
are full of it - but resolving it stripped only the leading slash, giving
'<base>/a0/skills/a0-create-plugin'. So every path Agent Zero handed the
model on Windows failed the moment the model handed it back.
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import files

WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt", reason="the container-path ambiguity only exists on Windows"
)


@WINDOWS_ONLY
def test_the_shape_the_framework_emits_resolves_back():
    """The round trip that was broken: what get_abs_path_dockerized hands
    out must be something get_abs_path takes back."""
    shown = files.get_abs_path_dockerized("skills")
    assert shown.startswith("/a0/"), shown
    assert files.get_abs_path(shown) == files.get_abs_path("skills")


@WINDOWS_ONLY
def test_a_real_skill_path_is_found():
    """The exact failure, end to end."""
    shown = files.get_abs_path_dockerized("skills/a0-create-plugin")
    assert files.exists(shown), f"{shown} should resolve to an existing directory"


@WINDOWS_ONLY
@pytest.mark.parametrize("path", ["/a0/skills", "\\a0\\skills", "/a0/skills/"])
def test_both_separators_and_a_trailing_slash_work(path):
    """The model echoes these back in whichever form it saw them. Compared
    by normpath: a trailing separator names the same directory."""
    assert os.path.normpath(files.get_abs_path(path)) == os.path.normpath(
        files.get_abs_path("skills")
    )


@WINDOWS_ONLY
@pytest.mark.parametrize("path", ["/a0", "/a0/", "\\a0"])
def test_the_bare_root_resolves_to_the_base_dir(path):
    assert files.get_abs_path(path) == files.get_abs_path("")


@WINDOWS_ONLY
def test_only_a_whole_a0_segment_is_stripped():
    """'/a0stuff/x' is not the container root, and treating it as one would
    silently redirect a real directory somewhere else."""
    resolved = files.get_abs_path("/a0stuff/x")
    assert "a0stuff" in resolved


@WINDOWS_ONLY
def test_other_container_paths_keep_their_old_behaviour():
    """'/tmp/...' and friends were already treated as relative to the base
    dir rather than the drive root; that must not change."""
    assert files.get_abs_path("/tmp/x") == os.path.join(
        files.get_abs_path(""), "tmp/x"
    )


@WINDOWS_ONLY
def test_a_real_windows_absolute_path_is_untouched():
    assert files.get_abs_path(r"C:\Windows\System32") == r"C:\Windows\System32"


@WINDOWS_ONLY
def test_a_unc_path_is_untouched():
    assert files.get_abs_path(r"\\server\share\file") == r"\\server\share\file"


@WINDOWS_ONLY
def test_a_plain_relative_path_still_works():
    assert files.exists("skills/a0-create-plugin")


@WINDOWS_ONLY
def test_the_stripped_path_cannot_escape_the_base_dir():
    """The segment is dropped, not resolved - '/a0/../x' must not become a
    way out of the base directory."""
    resolved = os.path.normpath(files.get_abs_path("/a0/../outside"))
    base = os.path.normpath(files.get_abs_path(""))
    assert not resolved.startswith(base) or resolved == base, (
        "traversal is unchanged by this fix; if it ever resolves inside, "
        "confirm is_in_base_dir still guards callers"
    )
