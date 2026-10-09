import pytest
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))



def read(*parts: str) -> str:
    return PROJECT_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_file_browser_remember_last_directory_defaults_enabled() -> None:
    settings_source = read("helpers", "settings.py")

    assert "file_browser_remember_last_directory: bool" in settings_source
    assert "file_browser_remember_last_directory=get_default_value(" in settings_source
    assert '"file_browser_remember_last_directory",\n            True,' in settings_source


def test_file_browser_keeps_the_public_api_other_features_call() -> None:
    store = read("webui", "components", "modals", "file-browser", "file-browser-store.js")

    # Called by chat input, projects, plugins, skills, settings, welcome, Editor,
    # Desktop, Office, Commands and Time Travel (see the file-browser AGENTS.md).
    for signature in (
        "async open(path = \"\", options = {})",
        "async openSurface(path = \"\")",
        "async openTextPicker(path = \"\", onConfirm = null)",
        "async openSaveAsPicker(path = \"\", options = {})",
        "async openRenameModal(file, options = {})",
        "downloadFile(file)",
        "handleClose()",
        "onMount(element = null, options = {})",
        "onUnmount()",
        "beginSurfaceHandoff()",
        "finishSurfaceHandoff()",
        "cancelSurfaceHandoff()",
    ):
        assert signature in store, signature
    assert 'createStore("fileBrowser", model)' in store
    assert "window.openFileLink = async function (path)" in store


def test_file_browser_uses_only_the_policy_checked_backend() -> None:
    store = read("webui", "components", "modals", "file-browser", "file-browser-store.js")

    assert 'callJsonApi("file_manager"' in store
    assert '"/api/file_manager_upload"' in store
    assert "/api/file_manager_download?" in store
    for legacy in ("get_work_dir_files", "delete_work_dir_file", "rename_work_dir_file",
                   "upload_work_dir_files", "download_work_dir_file", "edit_work_dir_file"):
        assert legacy not in store, legacy
    # Old-style paths from other features are translated server-side.
    assert 'this.api("locate", { path: candidate })' in store


def test_file_browser_remembers_the_last_folder_only_when_the_setting_allows() -> None:
    store = read("webui", "components", "modals", "file-browser", "file-browser-store.js")
    workdir_settings = read("webui", "components", "settings", "agent", "workdir.html")

    assert "file_browser_remember_last_directory" in store
    assert "if (!this.rememberLastDirectory) return \"\";" in store
    assert "Remember last file browser location" in workdir_settings


def test_file_browser_editor_picker_modes() -> None:
    html = read("webui", "components", "modals", "file-browser", "file-browser.html")
    store = read("webui", "components", "modals", "file-browser", "file-browser-store.js")

    assert 'const EDITOR_TEXT_EXTENSIONS = new Set(["md", "txt"]);' in store
    assert '"Open Selected"' in store and '"Save Here"' in store
    # Open picker lists only folders and .md/.txt; Save As returns a Windows path.
    assert "this.pickerMode === PICKER_TEXT_OPEN && !entry.is_dir && !this.isEditorText(entry)" in store
    assert "path: joinPath(this.path, filename)" in store
    assert "$store.fileBrowser.confirmPicker()" in html
    assert "$store.fileBrowser.isSaveAsPicker()" in html
    assert 'x-show="!fb.isPickerMode()"' in html  # no editing commands while picking


def test_file_browser_downloads_natively_without_loading_files_into_the_page() -> None:
    store = read("webui", "components", "modals", "file-browser", "file-browser-store.js")
    download = store[store.index("  download(entries = this.selectedEntries) {"):store.index("  // Used by window.openFileLink")]

    assert "link.href = this.downloadUrl(" in download
    assert "blob" not in download.lower() and "fetch" not in download
    assert "Preparing the ZIP" in download


def test_file_browser_layout_drops_columns_and_panes_as_it_narrows() -> None:
    html = read("webui", "components", "modals", "file-browser", "file-browser.html")

    assert "container: fb-list / inline-size;" in html
    assert "@container fb-list (max-width: 620px)" in html  # Type column goes first
    assert "@container fb-list (max-width: 440px)" in html  # then Date modified
    assert "@container fb-root (max-width: 760px) { .fb-preview { display: none; } }" in html
    assert "@container fb-root (max-width: 520px)" in html  # navigation pane overlays


def test_file_browser_is_registered_as_right_canvas_surface() -> None:
    html = read("webui", "components", "modals", "file-browser", "file-browser.html")
    store = read("webui", "components", "modals", "file-browser", "file-browser-store.js")
    surfaces = read("webui", "js", "surfaces.js")
    register = read("extensions", "webui", "right_canvas_register_surfaces", "register-files.js")
    panel = read("extensions", "webui", "right-canvas-panels", "files-panel.html")
    input_store = read("webui", "components", "chat", "input", "input-store.js")
    welcome_store = read("webui", "components", "welcome", "welcome-store.js")

    assert 'id: "files"' in surfaces
    assert 'title: "Files"' in surfaces
    assert 'modalPath: "modals/file-browser/file-browser.html"' in surfaces
    assert 'await store.openSurface(payload.path || payload.filePath || payload.directory || "")' in surfaces
    assert 'data-surface-id="files"' in html
    assert 'data-surface-modal-path="modals/file-browser/file-browser.html"' in html
    assert 'class="surface-modal file-browser-modal modal-no-backdrop"' in html
    assert 'class="file-browser-modal-body"' in html
    assert 'x-create="$store.fileBrowser.onMount($el, xAttrs($el) || {})"' in html
    assert 'x-destroy="$store.fileBrowser.onUnmount(xAttrs($el) || {})"' in html
    assert ".modal-inner.file-browser-modal" in html
    assert "resize: both" in html
    assert "openSurface(path" in store
    assert "setupFloatingSurfaceModalChrome" in store
    assert 'focusButtonClass: "file-browser-modal-focus-button"' in store
    assert "beginSurfaceHandoff()" in store
    assert "finishSurfaceHandoff()" in store
    assert 'id: "files"' in register
    assert "fileBrowserStore.openSurface" in register
    assert 'data-surface-id="files"' in panel
    assert 'path="modals/file-browser/file-browser.html" mode="canvas"' in panel
    assert 'openLatestSurface("files"' in input_store
    assert 'import { store as fileBrowserStore } from "/components/modals/file-browser/file-browser-store.js";' in welcome_store
    assert "fileBrowserStore.open()" in welcome_store
    assert "chatInputStore.browseFiles" not in welcome_store
