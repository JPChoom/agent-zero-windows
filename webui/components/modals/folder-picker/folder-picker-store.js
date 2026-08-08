import { createStore } from "/js/AlpineStore.js";
import { fetchApi } from "/js/api.js";

const FOLDER_PICKER_MODAL_PATH = "modals/folder-picker/folder-picker.html";

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);
}

// A small, purpose-built folder browser for picking one absolute path
// outside the workdir (e.g. adding an external project root to the
// tiered filesystem-access setting). Deliberately separate from
// file-browser-store.js: that store's whole model is paths relative to a
// single workdir base_dir, with a lot of surface area (rename/delete/
// upload/bulk actions/surface handoff) that doesn't apply here and would
// be risky to bend into an absolute-path, folder-only mode.
const model = {
  isLoading: false,
  currentPath: "",
  parentPath: "",
  entries: [],
  error: "",
  onConfirm: null,
  closePromise: null,

  async open(initialPath = "", onConfirm = null) {
    this.reset();
    this.onConfirm = typeof onConfirm === "function" ? onConfirm : null;
    this.closePromise = window.openModal(FOLDER_PICKER_MODAL_PATH);
    await this.fetchFolders(initialPath);
    await this.closePromise;
  },

  async fetchFolders(path = "") {
    this.isLoading = true;
    this.error = "";
    try {
      const resp = await fetchApi(
        `/get_folder_browser_files?path=${encodeURIComponent(path || "")}`
      );
      const data = await resp.json().catch(() => ({}));
      const result = data.data || {};
      if (resp.ok && !result.error) {
        this.entries = result.entries || [];
        this.currentPath = result.current_path || "";
        this.parentPath = result.parent_path || "";
      } else {
        this.error = result.error || "Failed to list folder";
      }
    } catch (e) {
      this.error = e?.message || "Failed to list folder";
    } finally {
      this.isLoading = false;
    }
  },

  async navigateTo(path) {
    await this.fetchFolders(path);
  },

  async navigateUp() {
    if (this.currentPath) {
      await this.fetchFolders(this.parentPath);
    }
  },

  // Rendered via x-html + event delegation (see onEntryClick), not x-for:
  // the modal system removes a closed modal's DOM with a raw
  // element.remove() (webui/js/modals.js's closeModal()), bypassing
  // Alpine's own teardown - a stale x-for effect from a previous open()
  // can then fire against already-removed nodes on the next store update
  // ("Cannot read properties of undefined (reading 'after')"), corrupting
  // Alpine badly enough to blank out an unrelated modal opened right
  // after. x-html has no per-item DOM to reconcile, so there's nothing
  // for a stale effect to break.
  get entriesHtml() {
    return this.entries
      .map((entry) => {
        const path = escapeHtml(entry.path);
        const name = escapeHtml(entry.name);
        return (
          `<button type="button" class="folder-picker-entry" data-entry-path="${path}">` +
          `<span class="material-symbols-outlined">folder</span><span>${name}</span>` +
          `</button>`
        );
      })
      .join("");
  },

  onEntryClick(event) {
    if (this.isLoading) return;
    const target = event.target.closest("[data-entry-path]");
    if (!target) return;
    this.navigateTo(target.getAttribute("data-entry-path"));
  },

  canConfirm() {
    return Boolean(this.currentPath) && !this.isLoading;
  },

  confirm() {
    if (!this.canConfirm()) return;
    const path = this.currentPath;
    const onConfirm = this.onConfirm;
    this.reset();
    window.closeModal(FOLDER_PICKER_MODAL_PATH);
    onConfirm?.(path);
  },

  cancel() {
    this.reset();
    window.closeModal(FOLDER_PICKER_MODAL_PATH);
  },

  reset() {
    // Clear the rendered list (and its x-for-tracked DOM nodes) while the
    // modal is still open/visible, before window.closeModal() removes the
    // underlying DOM - otherwise Alpine's x-for can be left holding
    // references to nodes that vanished out from under it, and the next
    // open() throws reconciling against them ("Cannot read properties of
    // undefined (reading 'after')"), which was observed to corrupt Alpine
    // state badly enough to blank out an unrelated modal opened right after.
    this.error = "";
    this.entries = [];
    this.currentPath = "";
    this.parentPath = "";
    this.onConfirm = null;
  },
};

export const store = createStore("folderPicker", model);
