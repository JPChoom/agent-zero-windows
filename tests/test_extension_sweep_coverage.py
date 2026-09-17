"""Structural guard for the full best_effort sweep.

Each of these extensions was judged, individually, to be either:
  (a) a "nice to have" enrichment reading a live external dependency
      (filesystem, a remote server, an embedding search), or
  (b) bookkeeping that runs after the tool's real effect already
      happened (an edit already written, a websocket already
      disconnecting) - where the tool's actual result must not be lost
      because a side-channel recorder tripped.

call_extensions_async has no generic per-extension error handling, so
without the decorator any one of these throwing aborts every extension
still queued at that call site - for system_prompt extensions, every
future turn until fixed; for the rest, at minimum the current turn, and
for the tool_execute_after/*_after ones, it also means the tool's own
successful response never reaches the model.

This does not re-verify best_effort's own behaviour (see
test_extension_best_effort.py) or each extension's own logic (existing
suites) - only that the decorator is actually present on the method that
needs it, so a future edit cannot silently drop it.
"""

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TARGETS = [
    "extensions/python/system_prompt/_12_mcp_prompt.py",
    "extensions/python/system_prompt/_13_skills_prompt.py",
    "extensions/python/system_prompt/_14_project_prompt.py",
    "plugins/_memory/extensions/python/system_prompt/_20_behaviour_prompt.py",
    "plugins/_email_integration/extensions/python/system_prompt/_20_email_context.py",
    "plugins/_whatsapp_integration/extensions/python/system_prompt/_20_wa_context.py",
    "plugins/_telegram_integration/extensions/python/system_prompt/_20_telegram_context.py",
    "extensions/python/message_loop_prompts_after/_75_include_workdir_extras.py",
    "extensions/python/message_loop_prompts_after/_63_recall_relevant_skills.py",
    "extensions/python/message_loop_prompts_after/_65_include_loaded_skills.py",
    "extensions/python/message_loop_prompts_after/_72_include_parallel_jobs.py",
    "extensions/python/message_loop_prompts_after/_70_include_agent_info.py",
    "extensions/python/message_loop_prompts_after/_60_include_current_datetime.py",
    "plugins/_skills/extensions/python/message_loop_prompts_after/_66_include_active_skills.py",
    "plugins/_editor/extensions/python/message_loop_prompts_after/_55_include_editor_open_files.py",
    "plugins/_a0_connector/extensions/python/message_loop_prompts_after/_76_include_remote_file_structure.py",
    "plugins/_desktop/extensions/python/message_loop_prompts_after/_55_include_desktop_state.py",
    "plugins/_coding_controller/extensions/python/text_editor_patch_after/_15_track_edit.py",
    "plugins/_coding_controller/extensions/python/text_editor_write_after/_15_track_edit.py",
    "plugins/_editor/extensions/python/text_editor_write_after/_40_sync_open_sessions.py",
    "plugins/_editor/extensions/python/text_editor_patch_after/_40_sync_open_sessions.py",
    "plugins/_editor/extensions/python/workdir_file_mutation_after/_40_sync_open_sessions.py",
    "plugins/_time_travel/extensions/python/text_editor_write_after/_50_snapshot.py",
    "plugins/_time_travel/extensions/python/text_editor_patch_after/_50_snapshot.py",
    "plugins/_time_travel/extensions/python/tool_execute_after/_50_code_execution_snapshot.py",
    "plugins/_time_travel/extensions/python/workdir_file_mutation_after/_50_snapshot.py",
    "plugins/_browser/extensions/python/webui_ws_disconnect/_50_browser.py",
    "plugins/_editor/extensions/python/webui_ws_disconnect/_50_editor.py",
    "plugins/_office/extensions/python/webui_ws_disconnect/_50_office.py",
]

DECORATED_EXECUTE = re.compile(r'@best_effort\("[^"]+"\)\s*\n\s*async def execute\(')


@pytest.mark.parametrize("rel_path", TARGETS)
def test_execute_is_decorated(rel_path):
    text = (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
    assert "from helpers.extension import" in text and "best_effort" in text, (
        f"{rel_path} does not import best_effort"
    )
    assert DECORATED_EXECUTE.search(text), (
        f"{rel_path}: execute() is not decorated with @best_effort(...) "
        "immediately above it"
    )


def test_the_target_list_itself_has_no_duplicates():
    assert len(TARGETS) == len(set(TARGETS))


def test_every_target_file_still_exists():
    missing = [p for p in TARGETS if not (PROJECT_ROOT / p).exists()]
    assert not missing, f"sweep target(s) no longer exist: {missing}"
