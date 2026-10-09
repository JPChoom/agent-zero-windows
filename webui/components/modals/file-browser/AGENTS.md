# File Browser Modal DOX

## Purpose

- Own the Windows File Browser (Explorer-style) for the modal and right-canvas Files surface, plus the Editor's Open / Save As pickers and the shared rename / new-item dialog.

## Ownership

- `file-browser.html` owns the layout (navigation bar with back/forward/up/refresh, editable address bar with breadcrumbs, search; command bar; navigation pane with Quick access and This PC drives; details list; preview pane; status bar; context menu; confirm dialog; built-in text editor), scoped styles and the picker footer.
- `file-browser-store.js` (`$store.fileBrowser`) owns loading, selection, history, clipboard, file operations, uploads, downloads, preview, text editing, keyboard handling and picker state.
- `rename-modal.html` owns the name dialog for rename, new folder and new file; it reuses the store.

## Local Contracts

- Backend is only `api/file_manager.py`, `api/file_manager_upload.py` and `api/file_manager_download.py`; every path is checked by `helpers/file_access.py`. The legacy work-dir endpoints were removed; `/api/download_work_dir_file` remains only for links built elsewhere (attachments, message file links, Office) and goes through the same checks.
- Paths are absolute Windows paths. Callers may pass `""`, `$WORK_DIR`, Docker-style `/a0/...`, workdir-relative names or a Windows file/folder path; `openPath` resolves them with the `locate` action (a file opens its folder with the file selected), falling back to the remembered folder and then the workdir.
- Public API used by other features (keep signatures): `open(path, options)` (awaits close), `openSurface(path)` (canvas, no modal), `openTextPicker(path, onConfirm)`, `openSaveAsPicker(path, {filename, defaultExtension, onConfirm})`, `openRenameModal(file, {currentPath, entries, validateName, performRename, onRenamed})`, `downloadFile(file)`, `handleClose()`, `onMount` / `onUnmount`, `begin/finish/cancelSurfaceHandoff`, and `window.openFileLink(path)`.
- Picker payloads: Open -> `{mode, directory, selectedFiles}` (only `.md` / `.txt`; the list shows only folders and those files); Save As -> `{mode, directory, filename, path}` with `path` a Windows path. Returning `false` from `onConfirm` keeps the picker open.
- The floating modal uses the shared surface chrome (draggable/resizable, Focus mode). Overlays (context menu, dialogs, editor) are positioned inside `.fb`, not `position: fixed`, because the modal is transformed.
- Keyboard: handled on `.fb`; while the Files modal is top of the modal stack, keys pressed with nothing focused (after a dialog closes) are routed to it too, never when text is selected. Shortcuts: Enter, Backspace / Alt+Up, Alt+Left / Alt+Right, F2, F5, Del (Recycle Bin), Shift+Del (permanent), Ctrl+A / C / X / V, Ctrl+Shift+N, Ctrl+L / Alt+D, arrows / Home / End (Shift extends), type-ahead.
- Uploads: files or whole folders (drop, or the Upload / Upload folder buttons); folder structure and empty folders are kept, a top-level folder whose name is taken becomes `Name (2)`, large uploads go in batches (256 MB / 500 files) with one progress bar. Dropping onto a folder row or a navigation-pane place uploads into it.
- Dragging rows: dropping on a folder (row or navigation pane) moves the items, Ctrl copies; dragging out of the browser sets `DownloadURL`, so Chrome/Edge download the file, or a ZIP for folders/multiple items, where it is dropped (other browsers ignore it).
- Delete always asks first; it says when a drive has no Recycle Bin. Downloads are native browser downloads of a GET URL (no blobs in page memory); folders and multi-selections arrive as one ZIP.
- The built-in text editor (any text file up to 2 MB) saves with the file's encoding and line endings (`newline` from `read_text`) and refuses to overwrite a file changed on disk.
- Remembered folder (localStorage `fileBrowser.lastDirectory`) only while settings `file_browser_remember_last_directory` is on. View preferences (panes, hidden items, sort) live in localStorage `fileBrowser.prefs`; on screens 600 px wide or less the navigation pane starts closed.
- Narrow layouts: the list drops Type, then Date modified (`fb-list` container queries); the window hides the preview pane, then command labels, then overlays the navigation pane (`fb-root`).

## Work Guidance

- Share markup and store behavior between modal and canvas modes; branch only on explicit component `mode`.
- Show refusals from the backend as they are (they explain the access setting); do not re-implement access rules in the frontend.

## Verification

- `pytest tests/test_file_browser_navigation.py tests/test_file_manager.py tests/test_file_access.py`
- Smoke-test in the dev server: open Files as a modal and in the canvas, rename (F2), copy/paste, delete to the Recycle Bin, upload, download a folder, edit a text file, the Editor Open/Save As pickers, and a phone-width viewport.

## Child DOX Index

No child DOX files.
