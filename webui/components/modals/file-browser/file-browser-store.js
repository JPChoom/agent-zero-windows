import { createStore } from "/js/AlpineStore.js";
import { callJsonApi, getCsrfToken } from "/js/api.js";
import { getModalStack } from "/js/modals.js";
import {
  openLatest as openLatestSurface,
  setupFloatingSurfaceModalChrome,
} from "/js/surfaces.js";

// Windows File Browser (Explorer-style). Backend: api/file_manager*.py, every
// path checked by helpers/file_access.py. Paths are absolute Windows paths.

const MODAL_PATH = "modals/file-browser/file-browser.html";
const RENAME_MODAL_PATH = "modals/file-browser/rename-modal.html";
const PREFS_KEY = "fileBrowser.prefs";
const LAST_DIR_KEY = "fileBrowser.lastDirectory";
const PICKER_NONE = "";
const PICKER_TEXT_OPEN = "text-open";
const PICKER_SAVE_AS = "save-as";
const EDITOR_TEXT_EXTENSIONS = new Set(["md", "txt"]);
const DESKTOP_EXTENSIONS = new Set(["odt", "ods", "odp", "docx", "xlsx", "pptx"]);
const BROWSER_EXTENSIONS = new Set(["html", "htm", "xhtml", "svg", "xml", "pdf", "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico"]);
const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico"]);
const TEXT_EXTENSIONS = new Set([
  "txt", "md", "log", "csv", "tsv", "json", "jsonl", "yaml", "yml", "toml", "ini", "cfg", "conf", "env", "xml",
  "html", "htm", "css", "scss", "js", "mjs", "cjs", "ts", "tsx", "jsx", "py", "pyw", "ps1", "psm1", "bat", "cmd",
  "sh", "c", "h", "cpp", "hpp", "cs", "java", "go", "rs", "rb", "php", "sql", "lua", "r", "gitignore", "editorconfig",
]);
const ICONS = [
  [["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "svg", "tif", "tiff", "heic"], "image"],
  [["mp4", "mkv", "avi", "mov", "webm", "wmv"], "movie"],
  [["mp3", "wav", "flac", "ogg", "m4a", "aac"], "music_note"],
  [["pdf"], "picture_as_pdf"],
  [["zip", "7z", "rar", "tar", "gz", "bz2", "xz"], "folder_zip"],
  [["csv", "tsv", "xlsx", "xls", "ods"], "table_chart"],
  [["pptx", "ppt", "odp"], "slideshow"],
  [["docx", "doc", "odt", "rtf"], "article"],
  [["md", "txt", "log"], "description"],
  [["ps1", "psm1", "bat", "cmd", "sh"], "terminal"],
  [["ini", "cfg", "conf", "yaml", "yml", "toml", "env", "json", "jsonl", "xml"], "settings"],
  [["exe", "msi", "dll", "sys"], "apps"],
  [["py", "js", "mjs", "ts", "tsx", "jsx", "html", "htm", "css", "c", "cpp", "h", "cs", "java", "go", "rs", "rb", "php", "sql", "lua"], "code"],
];
const ICON_BY_EXT = new Map(ICONS.flatMap(([exts, icon]) => exts.map((ext) => [ext, icon])));
const SURFACE_ACTIONS = {
  editor: { label: "Open in Editor", icon: "article" },
  desktop: { label: "Open in Desktop", icon: "desktop_windows" },
  browser: { label: "Open in Browser", icon: "language" },
};

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function joinPath(folder, name) {
  const base = String(folder || "");
  return /[\\/]$/.test(base) ? base + name : `${base}\\${name}`;
}

function lastSeparator(path) {
  return Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
}

function parentOf(path) {
  const text = String(path || "").replace(/[\\/]+$/, "");
  const index = lastSeparator(text);
  if (index < 0) return "";
  if (/^[A-Za-z]:$/.test(text.slice(0, index))) return text.slice(0, index + 1);
  return text.slice(0, index) || "/";
}

function siblingOf(path, name) {
  const text = String(path || "");
  const index = lastSeparator(text);
  return index < 0 ? name : text.slice(0, index + 1) + name;
}

function extensionOf(name) {
  const text = String(name || "").toLowerCase();
  const index = text.lastIndexOf(".");
  return index > 0 ? text.slice(index + 1) : text.startsWith(".") ? text.slice(1) : "";
}

const model = {
  // --- state ---------------------------------------------------------------
  isLoading: false,
  error: "",
  rememberLastDirectory: true,
  path: "",
  parent: "",
  entries: [],
  hiddenCount: 0,
  truncated: false,
  writable: true,
  driveKind: "",
  places: { quick: [], drives: [], policy: null },
  selected: {},
  anchorPath: "",
  focusPath: "",
  back: [],
  forward: [],
  sortKey: "name",
  sortDir: 1,
  searchQuery: "",
  editingAddress: false,
  addressInput: "",
  showHidden: false,
  showPreview: false,
  showNav: true,
  clipboard: null,
  menu: null,
  confirm: null,
  uploads: [],
  dragOver: false,
  dragPaths: null,
  dropTarget: "",
  preview: null,
  textEditor: null,
  closePromise: null,
  isSurfaceHandoff: false,
  surfaceHandoffPath: "",
  _floatingCleanup: null,
  _mountedLoadTimer: null,
  _typeAhead: "",
  _typeAheadTimer: null,

  // Picker modes used by the Editor plugin (Open..., Save As...).
  pickerMode: PICKER_NONE,
  pickerConfirmLabel: "",
  pickerFilename: "",
  pickerDefaultExtension: "md",
  pickerFilenameError: "",
  pickerOnConfirm: null,
  isBulkBusy: false,

  // Rename / new-folder dialog (rename-modal.html); also used by Editor and Desktop.
  renameTarget: null,
  renameName: "",
  renameMode: "rename",
  isRenaming: false,
  renameError: null,
  renameAfterConfirm: null,
  renamePerformAction: null,
  renameValidateName: null,
  _renameEntries: null,
  _renameFolder: "",

  init() {
    document.addEventListener("settings-updated", (event) => {
      const value = event?.detail?.file_browser_remember_last_directory;
      if (typeof value !== "boolean") return;
      this.rememberLastDirectory = value;
      if (!value) this.rememberDirectory("");
    });
    const prefs = loadPrefs();
    this.showHidden = Boolean(prefs.showHidden);
    this.showPreview = Boolean(prefs.showPreview);
    this.showNav = prefs.showNav !== false;
    if (["name", "modified", "size", "type"].includes(prefs.sortKey)) this.sortKey = prefs.sortKey;
    this.sortDir = prefs.sortDir === -1 ? -1 : 1;
  },

  savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        showHidden: this.showHidden, showPreview: this.showPreview, showNav: this.showNav,
        sortKey: this.sortKey, sortDir: this.sortDir,
      }));
    } catch {}
  },

  // --- mounting --------------------------------------------------------------
  onMount(element = null, options = {}) {
    this._floatingCleanup?.();
    this._floatingCleanup = null;
    if (options?.mode === "canvas") {
      this.scheduleMountedLoad();
    } else {
      this._floatingCleanup = setupFloatingSurfaceModalChrome({
        root: element,
        modalClass: "file-browser-modal",
        focusButtonClass: "file-browser-modal-focus-button",
        minWidth: 420,
        minHeight: 360,
      });
    }
  },

  onUnmount() {
    this._floatingCleanup?.();
    this._floatingCleanup = null;
    this.cancelMountedLoad();
  },

  scheduleMountedLoad() {
    this.cancelMountedLoad();
    this._mountedLoadTimer = setTimeout(async () => {
      this._mountedLoadTimer = null;
      if (this.isLoading || (this.path && this.entries.length)) return;
      await this.openPath(this.path || "");
    }, 120);
  },

  cancelMountedLoad() {
    if (this._mountedLoadTimer) clearTimeout(this._mountedLoadTimer);
    this._mountedLoadTimer = null;
  },

  // --- public API (other features call these) --------------------------------
  async open(path = "", options = {}) {
    if (this.closePromise) return;
    this.configurePicker(options);
    this.closePromise = window.openModal(MODAL_PATH);
    try {
      await this.openPath(path);
      await this.closePromise;
    } finally {
      this.closePromise = null;
      if (!this.isSurfaceHandoff) this.destroy();
    }
  },

  async openSurface(path = "") {
    this.configurePicker({});
    return await this.openPath(path || this.surfaceHandoffPath || this.path);
  },

  async openTextPicker(path = "", onConfirm = null) {
    return await this.open(path, { pickerMode: PICKER_TEXT_OPEN, confirmLabel: "Open Selected", onConfirm });
  },

  async openSaveAsPicker(path = "", options = {}) {
    return await this.open(path, {
      pickerMode: PICKER_SAVE_AS,
      confirmLabel: "Save Here",
      filename: options.filename || "Untitled.md",
      defaultExtension: options.defaultExtension || "",
      onConfirm: options.onConfirm,
    });
  },

  handleClose() {
    window.closeModal(MODAL_PATH);
  },

  destroy() {
    this.cancelMountedLoad();
    this.menu = null;
    this.confirm = null;
    this.preview = null;
    this.textEditor = null;
    this.searchQuery = "";
    this.editingAddress = false;
    this.selected = {};
    this.isSurfaceHandoff = false;
    this.surfaceHandoffPath = "";
    this.resetPicker();
  },

  beginSurfaceHandoff() {
    this.isSurfaceHandoff = true;
    this.surfaceHandoffPath = this.path;
  },

  finishSurfaceHandoff() {
    this.isSurfaceHandoff = false;
    this.surfaceHandoffPath = "";
  },

  cancelSurfaceHandoff() {
    this.finishSurfaceHandoff();
  },

  // --- loading ------------------------------------------------------------------
  async api(action, payload = {}) {
    const result = await callJsonApi("file_manager", { action, ...payload });
    if (!result?.ok) throw new Error(result?.error || "The File Browser request failed.");
    return result;
  },

  async loadPlaces() {
    try {
      this.places = await this.api("places");
    } catch (error) {
      console.warn("File Browser places:", error);
    }
  },

  // Settings > Workdir "Remember last file browser location" (default on).
  async loadRememberSetting() {
    const loaded = globalThis.Alpine?.store?.("settings")?.settings?.file_browser_remember_last_directory;
    if (typeof loaded === "boolean") return (this.rememberLastDirectory = loaded);
    try {
      const response = await callJsonApi("settings_get", null);
      const value = response?.settings?.file_browser_remember_last_directory;
      this.rememberLastDirectory = typeof value === "boolean" ? value : true;
    } catch {
      this.rememberLastDirectory = true;
    }
    return this.rememberLastDirectory;
  },

  rememberedDirectory() {
    if (!this.rememberLastDirectory) return "";
    try {
      return localStorage.getItem(LAST_DIR_KEY) || "";
    } catch {
      return "";
    }
  },

  rememberDirectory(path) {
    try {
      if (this.rememberLastDirectory) localStorage.setItem(LAST_DIR_KEY, path);
      else localStorage.removeItem(LAST_DIR_KEY);
    } catch {}
  },

  // Open whatever path form a caller passes ("", "$WORK_DIR", "/a0/...", a
  // workdir-relative name, a Windows folder or file path).
  async openPath(path = "") {
    if (window.innerWidth <= 600) this.showNav = false; // overlays the list on phones; not saved
    this.isLoading = true;
    this.error = "";
    const placesPromise = this.loadPlaces();
    await this.loadRememberSetting();
    const candidates = [path || this.rememberedDirectory(), ""].filter((value, index, list) => list.indexOf(value) === index);
    for (const candidate of candidates) {
      try {
        const where = await this.api("locate", { path: candidate });
        await this.navigate(where.folder, { history: false, select: where.select });
        await placesPromise;
        return true;
      } catch (error) {
        if (candidate === candidates[candidates.length - 1]) {
          this.error = error.message;
          this.isLoading = false;
          await placesPromise;
          return false;
        }
      }
    }
    return false;
  },

  async navigate(path, options = {}) {
    if (!path) return false;
    const previous = this.path;
    this.isLoading = true;
    try {
      const listing = await this.api("list", { path, show_hidden: this.showHidden });
      if (options.history !== false && previous && previous !== listing.path) {
        this.back.push(previous);
        this.forward = [];
      }
      const keep = previous === listing.path ? this.selected : {};
      this.path = listing.path;
      this.parent = listing.parent;
      this.entries = listing.entries;
      this.hiddenCount = listing.hidden_count;
      this.truncated = listing.truncated;
      this.writable = listing.writable;
      this.driveKind = listing.drive_kind;
      this.error = "";
      this.selected = {};
      for (const entry of this.entries) if (keep[entry.path]) this.selected[entry.path] = true;
      if (previous !== listing.path) this.searchQuery = "";
      if (options.select) this.selectOnly(options.select);
      this.addressInput = this.path;
      this.editingAddress = false;
      this.rememberDirectory(this.path);
      this.updatePreview();
      this.focusList();
      return true;
    } catch (error) {
      if (options.quiet) return false;
      this.error = error.message;
      window.toastFrontendError?.(error.message, "File Browser");
      return false;
    } finally {
      this.isLoading = false;
    }
  },

  refresh() {
    return this.navigate(this.path, { history: false });
  },

  goBack() {
    if (!this.back.length) return;
    this.forward.push(this.path);
    this.navigate(this.back.pop(), { history: false });
  },

  goForward() {
    if (!this.forward.length) return;
    this.back.push(this.path);
    this.navigate(this.forward.pop(), { history: false });
  },

  goUp() {
    if (this.parent) this.navigate(this.parent, { select: this.path });
  },

  startAddressEdit() {
    this.addressInput = this.path;
    this.editingAddress = true;
  },

  async submitAddress() {
    const value = this.addressInput.trim();
    if (!value || value === this.path) {
      this.editingAddress = false;
      return;
    }
    try {
      const where = await this.api("locate", { path: value });
      await this.navigate(where.folder, { select: where.select });
    } catch (error) {
      window.toastFrontendError?.(error.message, "File Browser");
    }
  },

  get breadcrumbs() {
    const path = this.path || "";
    const match = path.match(/^[A-Za-z]:\\?/);
    if (!match) return [];
    const root = match[0].endsWith("\\") ? match[0] : match[0] + "\\";
    const crumbs = [{ name: this.driveLabel(root), path: root }];
    let current = root;
    for (const part of path.slice(match[0].length).split("\\").filter(Boolean)) {
      current = joinPath(current, part);
      crumbs.push({ name: part, path: current });
    }
    return crumbs;
  },

  driveLabel(root) {
    const drive = (this.places.drives || []).find((d) => d.root.toLowerCase() === root.toLowerCase());
    const letter = root.slice(0, 2).toUpperCase();
    return drive?.label ? `${drive.label} (${letter})` : `Local Disk (${letter})`;
  },

  crumbAllowed(path) {
    const roots = this.places.policy?.roots || [];
    const p = path.toLowerCase().replace(/\\+$/, "");
    return roots.some((root) => {
      const r = root.toLowerCase().replace(/\\+$/, "");
      return p === r || p.startsWith(r + "\\");
    });
  },

  // --- view -------------------------------------------------------------------
  get visibleEntries() {
    const query = this.searchQuery.trim().toLowerCase();
    const list = this.entries.filter((entry) => {
      if (this.pickerMode === PICKER_TEXT_OPEN && !entry.is_dir && !this.isEditorText(entry)) return false;
      return !query || entry.name.toLowerCase().includes(query);
    });
    const key = this.sortKey;
    const dir = this.sortDir;
    return list.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      let diff = 0;
      if (key === "size") diff = a.size - b.size;
      else if (key === "modified") diff = a.modified - b.modified;
      else if (key === "type") diff = this.typeLabel(a).localeCompare(this.typeLabel(b));
      return dir * (diff || a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));
    });
  },

  sortBy(key) {
    if (this.sortKey === key) this.sortDir = -this.sortDir;
    else {
      this.sortKey = key;
      this.sortDir = key === "modified" ? -1 : 1;
    }
    this.savePrefs();
  },

  sortIndicator(key) {
    return this.sortKey === key ? (this.sortDir === 1 ? "arrow_upward" : "arrow_downward") : "";
  },

  toggleHidden() {
    this.showHidden = !this.showHidden;
    this.savePrefs();
    this.refresh();
  },

  togglePreview() {
    this.showPreview = !this.showPreview;
    this.savePrefs();
    this.updatePreview();
  },

  toggleNav() {
    this.showNav = !this.showNav;
    this.savePrefs();
  },

  isNarrow() {
    return (document.querySelector(".fb")?.clientWidth || 1000) <= 520;
  },

  // On narrow screens the navigation pane overlays the list; close it after a pick.
  navigateFromPane(path) {
    if (this.isNarrow()) this.showNav = false;
    return this.navigate(path);
  },

  iconFor(entry) {
    if (entry.is_dir) return entry.is_link ? "folder_special" : "folder";
    return ICON_BY_EXT.get(entry.ext) || "draft";
  },

  driveIcon(drive) {
    return drive.kind === "removable" ? "usb" : "hard_drive";
  },

  typeLabel(entry) {
    if (entry.is_dir) return "File folder";
    return entry.ext ? `${entry.ext.toUpperCase()} file` : "File";
  },

  formatSize(bytes) {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let value = bytes / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
  },

  formatDate(ms) {
    if (!ms) return "";
    return new Date(ms).toLocaleString(undefined, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  },

  driveUsage(drive) {
    return drive.total ? Math.round(((drive.total - drive.free) / drive.total) * 100) : 0;
  },

  get statusText() {
    const count = this.visibleEntries.length;
    let text = `${count} ${count === 1 ? "item" : "items"}`;
    const selected = this.selectedEntries;
    if (selected.length) {
      const size = selected.filter((e) => !e.is_dir).reduce((sum, e) => sum + e.size, 0);
      text += `   ${selected.length} selected` + (size ? `  ${this.formatSize(size)}` : "");
    }
    if (this.hiddenCount && !this.showHidden) text += `   ${this.hiddenCount} hidden`;
    if (this.truncated) text += "   (showing the first 10,000)";
    return text;
  },

  // --- selection -----------------------------------------------------------
  get selectedEntries() {
    return this.entries.filter((entry) => this.selected[entry.path]);
  },

  isSelected(entry) {
    return Boolean(this.selected[entry.path]);
  },

  selectOnly(path) {
    this.selected = path ? { [path]: true } : {};
    this.anchorPath = path;
    this.focusPath = path;
    if (path) this.scrollIntoView(path);
  },

  clickEntry(entry, event) {
    this.menu = null;
    if (this.pickerMode === PICKER_SAVE_AS && !entry.is_dir) this.pickerFilename = entry.name;
    const list = this.visibleEntries;
    if (event?.shiftKey && this.anchorPath) {
      const a = list.findIndex((e) => e.path === this.anchorPath);
      const b = list.findIndex((e) => e.path === entry.path);
      const [from, to] = a < b ? [a, b] : [b, a];
      const next = event.ctrlKey ? { ...this.selected } : {};
      for (const item of list.slice(from, to + 1)) next[item.path] = true;
      this.selected = next;
    } else if (event?.ctrlKey || event?.metaKey) {
      const next = { ...this.selected };
      if (next[entry.path]) delete next[entry.path];
      else next[entry.path] = true;
      this.selected = next;
      this.anchorPath = entry.path;
    } else {
      this.selectOnly(entry.path);
    }
    this.focusPath = entry.path;
    this.updatePreview();
  },

  selectAll() {
    const next = {};
    for (const entry of this.visibleEntries) next[entry.path] = true;
    this.selected = next;
  },

  clearSelection() {
    this.selected = {};
    this.updatePreview();
  },

  // --- opening --------------------------------------------------------------
  isEditorText(entry) {
    return !entry.is_dir && EDITOR_TEXT_EXTENSIONS.has(entry.ext);
  },

  isTextFile(entry) {
    return !entry.is_dir && (TEXT_EXTENSIONS.has(entry.ext) || entry.size === 0);
  },

  surfaceTarget(entry) {
    if (!entry || entry.is_dir) return "";
    if (EDITOR_TEXT_EXTENSIONS.has(entry.ext)) return "editor";
    if (BROWSER_EXTENSIONS.has(entry.ext)) return "browser";
    if (DESKTOP_EXTENSIONS.has(entry.ext)) return "desktop";
    return "";
  },

  surfaceAction(entry) {
    return SURFACE_ACTIONS[this.surfaceTarget(entry)] || null;
  },

  // Double-click / Enter: folders open, text files edit, others preview or download.
  activate(entry) {
    if (!entry) return;
    if (entry.is_dir) return this.navigate(entry.path);
    if (this.pickerMode === PICKER_TEXT_OPEN) {
      this.selectOnly(entry.path);
      return this.confirmPicker();
    }
    if (this.pickerMode === PICKER_SAVE_AS) {
      this.pickerFilename = entry.name;
      return;
    }
    if (this.isTextFile(entry)) return this.editText(entry);
    if (IMAGE_EXTENSIONS.has(entry.ext) || entry.ext === "pdf") {
      this.showPreview = true;
      this.selectOnly(entry.path);
      return this.updatePreview();
    }
    return this.download([entry]);
  },

  async openInSurface(entry) {
    const target = this.surfaceTarget(entry);
    if (!target) return;
    this.menu = null;
    try {
      if (target === "browser") {
        const url = "file:///" + entry.path.replace(/\\/g, "/").split("/").map(encodeURIComponent).join("/").replace(/^([A-Za-z])%3A/, "$1:");
        const { store: browserStore } = await import("/plugins/_browser/webui/browser-store.js");
        await openLatestSurface("browser", { url, source: "file-browser" });
        let opened = false;
        for (let attempt = 0; attempt < 40 && !opened; attempt += 1) {
          opened = await browserStore.openUrlIntent(url, { source: "file-browser" });
          if (!opened) await new Promise((resolve) => setTimeout(resolve, 75));
        }
        if (!opened) throw new Error("The Browser surface is unavailable.");
      } else {
        await openLatestSurface(target, { path: entry.path, source: "file-browser" });
        const module = target === "editor" ? "/plugins/_editor/webui/editor-store.js" : "/plugins/_desktop/webui/desktop-store.js";
        const { store: surfaceStore } = await import(module);
        const session = await surfaceStore.openPath(entry.path, { source: "file-browser" });
        if (!session || session.ok === false) {
          throw new Error(surfaceStore.error || "This file can't be opened there (only files in the workdir or a project).");
        }
      }
      if (this.closePromise) window.closeModal(MODAL_PATH);
    } catch (error) {
      window.toastFrontendError?.(error?.message || "Could not open the file", "File Browser");
    }
  },

  // --- preview pane ----------------------------------------------------------
  downloadUrl(paths, inline = false) {
    const query = paths.map((path) => "path=" + encodeURIComponent(path)).join("&");
    return `/api/file_manager_download?${query}${inline ? "&inline=1" : ""}`;
  },

  async updatePreview() {
    if (!this.showPreview) return;
    const selected = this.selectedEntries;
    const entry = selected.length === 1 ? selected[0] : null;
    if (!entry) {
      this.preview = selected.length ? { kind: "many", count: selected.length } : null;
      return;
    }
    const base = { kind: "info", entry };
    if (IMAGE_EXTENSIONS.has(entry.ext)) {
      this.preview = { ...base, kind: "image", url: this.downloadUrl([entry.path], true) };
    } else if (entry.ext === "pdf") {
      this.preview = { ...base, kind: "pdf", url: this.downloadUrl([entry.path], true) };
    } else if (this.isTextFile(entry) && entry.size <= 512 * 1024) {
      this.preview = { ...base, kind: "loading" };
      try {
        const text = await this.api("read_text", { path: entry.path });
        if (this.selectedEntries.length === 1 && this.selectedEntries[0].path === entry.path) {
          this.preview = { ...base, kind: "text", text: text.content.slice(0, 20000) };
        }
      } catch {
        this.preview = base;
      }
    } else {
      this.preview = base;
    }
  },

  // --- built-in text editor ----------------------------------------------------
  async editText(entry) {
    this.menu = null;
    try {
      const file = await this.api("read_text", { path: entry.path });
      this.textEditor = { ...file, name: entry.name, original: file.content, saving: false, error: "" };
    } catch (error) {
      window.toastFrontendError?.(error.message, "File Browser");
    }
  },

  get textEditorDirty() {
    return Boolean(this.textEditor && this.textEditor.content !== this.textEditor.original);
  },

  async saveText() {
    const editor = this.textEditor;
    if (!editor || editor.saving) return;
    editor.saving = true;
    editor.error = "";
    try {
      const result = await this.api("write_text", {
        path: editor.path, content: editor.content, encoding: editor.encoding,
        expected_modified: editor.modified, newline: editor.newline,
      });
      editor.modified = result.modified;
      editor.original = editor.content;
      window.toastFrontendSuccess?.(`Saved ${editor.name}`, "File Browser");
      this.refresh();
    } catch (error) {
      editor.error = error.message;
    } finally {
      editor.saving = false;
    }
  },

  closeTextEditor(force = false) {
    if (!force && this.textEditorDirty) {
      this.confirm = {
        title: "Discard changes?",
        message: `${this.textEditor.name} has unsaved changes.`,
        okLabel: "Discard",
        danger: true,
        run: () => { this.textEditor = null; this.focusList(); },
      };
      return;
    }
    this.textEditor = null;
    this.focusList();
  },

  // --- context menu ------------------------------------------------------------
  openMenu(event, entry = null) {
    if (entry && !this.isSelected(entry)) this.selectOnly(entry.path);
    if (!entry) this.clearSelection();
    // Positioned inside .fb (the draggable modal is transformed, so fixed
    // coordinates would be offset); kept within its bounds.
    const box = (event.currentTarget?.closest?.(".fb") || document.querySelector(".fb"))?.getBoundingClientRect();
    const width = 240;
    const height = entry ? 400 : 290;
    const left = box ? event.clientX - box.left : event.clientX;
    const top = box ? event.clientY - box.top : event.clientY;
    const maxX = (box?.width || window.innerWidth) - width - 6;
    const maxY = (box?.height || window.innerHeight) - height - 6;
    this.menu = { x: Math.max(6, Math.min(left, maxX)), y: Math.max(6, Math.min(top, maxY)), entry };
  },

  closeMenu() {
    this.menu = null;
  },

  // --- file operations ------------------------------------------------------
  async run(label, action, payload, after = null) {
    this.menu = null;
    try {
      const result = await this.api(action, payload);
      await this.refresh();
      after?.(result);
      return result;
    } catch (error) {
      window.toastFrontendError?.(error.message, label);
      return null;
    }
  },

  newFolder() {
    this.openNameDialog("create-folder", "New folder");
  },

  newTextFile() {
    this.openNameDialog("create-file", "New Text Document.txt");
  },

  openNameDialog(mode, suggested) {
    this.menu = null;
    this.resetRenameState();
    this.renameMode = mode;
    this.renameName = this.uniqueName(suggested);
    this._renameFolder = this.path;
    window.openModal(RENAME_MODAL_PATH);
  },

  uniqueName(name) {
    const names = new Set(this.entries.map((e) => e.name.toLowerCase()));
    if (!names.has(name.toLowerCase())) return name;
    const dot = name.lastIndexOf(".");
    const [stem, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
    for (let n = 2; ; n += 1) {
      const candidate = `${stem} (${n})${ext}`;
      if (!names.has(candidate.toLowerCase())) return candidate;
    }
  },

  renameSelected() {
    const [entry] = this.selectedEntries;
    if (entry) this.openRenameModal(entry);
  },

  // Also called by the Editor and Desktop plugins with their own performRename.
  async openRenameModal(file, options = {}) {
    this.menu = null;
    this.resetRenameState();
    this.renameTarget = file;
    this.renameName = file?.name || "";
    this.renameMode = "rename";
    this.renameAfterConfirm = typeof options.onRenamed === "function" ? options.onRenamed : null;
    this.renamePerformAction = typeof options.performRename === "function" ? options.performRename : null;
    this.renameValidateName = typeof options.validateName === "function" ? options.validateName : null;
    this._renameEntries = Array.isArray(options.entries) ? options.entries : null;
    this._renameFolder = options.currentPath || parentOf(file?.path || "") || this.path;
    window.openModal(RENAME_MODAL_PATH);
  },

  closeRenameModal() {
    window.closeModal(RENAME_MODAL_PATH);
    this.focusList();
  },

  resetRenameState() {
    this.renameTarget = null;
    this.renameName = "";
    this.renameMode = "rename";
    this.isRenaming = false;
    this.renameError = null;
    this.renameAfterConfirm = null;
    this.renamePerformAction = null;
    this.renameValidateName = null;
    this._renameEntries = null;
  },

  get renameTitle() {
    return { "create-folder": "New folder name", "create-file": "New file name" }[this.renameMode] || "New name";
  },

  async confirmRename() {
    if (this.isRenaming) return;
    const name = this.renameName.trim();
    const invalid = !name || name === "." || name === ".." || /[<>:"/\\|?*]/.test(name) || /[. ]$/.test(name);
    if (invalid) {
      this.renameError = 'Use a name without < > : " / \\ | ? * that does not end in a dot or space.';
      return;
    }
    if (this.renameValidateName) {
      const verdict = this.renameValidateName(name, this.renameTarget);
      if (verdict !== true) {
        this.renameError = typeof verdict === "string" ? verdict : "That name can't be used.";
        return;
      }
    }
    const siblings = this._renameEntries || (this._renameFolder === this.path ? this.entries : []);
    const clash = siblings.some((e) => e?.name?.toLowerCase() === name.toLowerCase() && e.path !== this.renameTarget?.path);
    if (clash) {
      this.renameError = `An item named "${name}" already exists.`;
      return;
    }
    this.isRenaming = true;
    this.renameError = null;
    const previousPath = this.renameTarget?.path || "";
    const newPath = this.renameMode === "rename" ? siblingOf(previousPath, name) : joinPath(this._renameFolder, name);
    try {
      let response = {};
      if (this.renamePerformAction) {
        response = (await this.renamePerformAction({
          action: this.renameMode, previousPath, path: newPath, name, target: this.renameTarget,
        })) || {};
        if (response.error || response.ok === false) throw new Error(response.error || "Rename failed");
      } else if (this.renameMode === "rename") {
        response = await this.api("rename", { path: previousPath, name });
      } else {
        response = await this.api(this.renameMode === "create-folder" ? "mkdir" : "new_file", { path: this._renameFolder, name });
      }
      this.closeRenameModal();
      if (this._renameFolder === this.path || this.renameMode !== "rename" || !this.renamePerformAction) {
        await this.refresh();
        this.selectOnly(response.renamed || response.created || newPath);
      }
      await this.renameAfterConfirm?.({ action: this.renameMode, previousPath, path: newPath, name, target: this.renameTarget, response });
    } catch (error) {
      this.renameError = error.message || "Rename failed";
    } finally {
      this.isRenaming = false;
    }
  },

  requestDelete(permanent = false) {
    const items = this.selectedEntries;
    if (!items.length) return;
    const removable = ["removable", "network"].includes(this.driveKind);
    const what = items.length === 1 ? `"${items[0].name}"` : `these ${items.length} items`;
    const forever = permanent || removable;
    this.menu = null;
    this.confirm = {
      title: forever ? "Delete permanently?" : "Move to Recycle Bin?",
      message: forever
        ? `Permanently delete ${what}?${removable && !permanent ? " This drive has no Recycle Bin." : ""} This can't be undone.`
        : `Move ${what} to the Recycle Bin? You can restore it from there.`,
      okLabel: forever ? "Delete" : "Move to Recycle Bin",
      danger: forever,
      run: () => this.run("Delete", "delete", { paths: items.map((e) => e.path), permanent }, (result) => {
        const count = result.deleted.length;
        window.toastFrontendSuccess?.(
          `${result.recycled ? "Moved to the Recycle Bin" : "Deleted"}: ${count} ${count === 1 ? "item" : "items"}`,
          "File Browser",
        );
      }),
    };
  },

  async confirmOk() {
    const action = this.confirm?.run;
    this.confirm = null;
    this.focusList();
    await action?.();
  },

  cancelConfirm() {
    this.confirm = null;
    this.focusList();
  },

  copySelection(cut = false) {
    const paths = this.selectedEntries.map((e) => e.path);
    if (!paths.length) return;
    this.clipboard = { mode: cut ? "move" : "copy", paths, from: this.path };
    this.menu = null;
    window.toastFrontendInfo?.(`${paths.length} ${paths.length === 1 ? "item" : "items"} ${cut ? "cut" : "copied"}. Paste in another folder.`, "File Browser", 3);
  },

  isCut(entry) {
    return this.clipboard?.mode === "move" && this.clipboard.paths.includes(entry.path);
  },

  async paste() {
    const clip = this.clipboard;
    if (!clip) return;
    const result = await this.run(clip.mode === "move" ? "Move" : "Copy", clip.mode, { paths: clip.paths, dest: this.path });
    if (result) {
      if (clip.mode === "move") this.clipboard = null;
      const next = {};
      for (const path of result.created) next[path] = true;
      this.selected = next;
    }
  },

  copyPaths() {
    const text = this.selectedEntries.map((e) => e.path).join("\n") || this.path;
    navigator.clipboard?.writeText(text).then(
      () => window.toastFrontendSuccess?.("Path copied", "File Browser", 2),
      () => window.toastFrontendError?.("Could not copy the path", "File Browser"),
    );
    this.menu = null;
  },

  reveal(entry = null) {
    this.run("Show in Explorer", "reveal", { path: (entry || this.selectedEntries[0])?.path || this.path });
  },

  get isRemote() {
    return Boolean(this.places.policy?.remote);
  },

  // --- download / upload ------------------------------------------------------
  download(entries = this.selectedEntries) {
    if (!entries.length) return;
    this.menu = null;
    const link = document.createElement("a");
    link.href = this.downloadUrl(entries.map((e) => e.path));
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
    const zipped = entries.length > 1 || entries[0].is_dir;
    if (zipped) window.toastFrontendInfo?.("Preparing the ZIP... large folders take a moment before the download starts.", "Download", 5);
  },

  // Used by window.openFileLink (chat path links).
  downloadFile(file) {
    if (!file?.path) return;
    this.download([{ path: file.path, name: file.name, is_dir: false }]);
  },

  pickUpload(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    this.upload({ files: files.map((file) => ({ file, rel: "" })), dirs: [] });
  },

  // "Upload folder" button (<input webkitdirectory>): each file carries its
  // path inside the chosen folder. Browsers leave empty folders out here.
  pickUploadFolder(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    this.upload({ files: files.map((file) => ({ file, rel: file.webkitRelativePath || file.name })), dirs: [] });
  },

  isOsFileDrag(event) {
    return Array.from(event.dataTransfer?.types || []).includes("Files") && !this.dragPaths;
  },

  // Files and folders dropped from Windows. Entries must be taken while the
  // drop event is live; the folder trees are read afterwards.
  async onDrop(event, dest = this.path) {
    this.dragOver = false;
    this.dropTarget = "";
    if (this.dragPaths) return this.dropInternal(event, dest);
    const entries = Array.from(event.dataTransfer?.items || [])
      .filter((item) => item.kind === "file")
      .map((item) => item.webkitGetAsEntry?.() || item.getAsFile?.())
      .filter(Boolean);
    const tree = { files: [], dirs: [] };
    try {
      for (const entry of entries) await this.readDropped(entry, "", tree);
    } catch (error) {
      window.toastFrontendError?.(`Could not read the dropped items: ${error.message || error}`, "Upload");
      return;
    }
    this.upload(tree, dest);
  },

  async readDropped(entry, prefix, tree) {
    if (entry instanceof File) {
      tree.files.push({ file: entry, rel: prefix + entry.name });
      return;
    }
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      tree.files.push({ file, rel: prefix + entry.name });
      return;
    }
    if (!entry.isDirectory) return;
    const rel = prefix + entry.name;
    tree.dirs.push(rel);
    const reader = entry.createReader();
    for (;;) {
      // readEntries returns at most ~100 entries per call; repeat until empty.
      const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
      if (!batch.length) break;
      for (const child of batch) await this.readDropped(child, rel + "/", tree);
    }
  },

  // Uploads keep folder structure. A top-level folder whose name is taken in
  // the destination becomes "Name (2)" (as Explorer does), so nothing merges
  // silently. Large uploads go in batches with one combined progress bar.
  async upload(tree, dest = this.path) {
    const items = tree.files || [];
    const dirs = tree.dirs || [];
    if (!items.length && !dirs.length) return;
    if (dest === this.path && !this.writable) {
      window.toastFrontendError?.("This folder is read-only.", "Upload");
      return;
    }
    let taken;
    try {
      const names = dest === this.path ? this.entries : (await this.api("list", { path: dest, show_hidden: true })).entries;
      taken = new Set(names.map((e) => e.name.toLowerCase()));
    } catch (error) {
      window.toastFrontendError?.(error.message, "Upload");
      return;
    }
    const topOf = (rel) => rel.split("/")[0];
    const rename = new Map();
    for (const rel of [...dirs, ...items.filter((i) => i.rel.includes("/")).map((i) => i.rel)]) {
      const top = topOf(rel);
      if (rename.has(top)) continue;
      let name = top;
      for (let n = 2; taken.has(name.toLowerCase()); n += 1) name = `${top} (${n})`;
      taken.add(name.toLowerCase());
      rename.set(top, name);
    }
    const mapRel = (rel) => {
      const parts = rel.split("/");
      if (!rename.has(parts[0]) || (parts.length === 1 && !dirs.includes(rel))) return rel;
      return [rename.get(parts[0]), ...parts.slice(1)].join("/");
    };
    const files = items.map((item) => ({ file: item.file, rel: item.rel ? mapRel(item.rel) : "" }));
    const folders = dirs.map(mapRel);

    const total = files.reduce((sum, item) => sum + item.file.size, 0) || 1;
    const label = rename.size === 1 ? [...rename.values()][0] : files.length === 1 ? files[0].file.name : `${files.length} files`;
    const job = { id: Date.now() + Math.random(), name: label, progress: 0, error: "" };
    this.uploads.push(job);
    const batches = [];
    let batch = [];
    let batchBytes = 0;
    for (const item of files) {
      if (batch.length && (batchBytes + item.file.size > 256 * 1024 * 1024 || batch.length >= 500)) {
        batches.push(batch);
        batch = [];
        batchBytes = 0;
      }
      batch.push(item);
      batchBytes += item.file.size;
    }
    if (batch.length || !batches.length) batches.push(batch);

    const saved = [];
    let sent = 0;
    try {
      const token = await getCsrfToken();
      for (const [index, part] of batches.entries()) {
        const form = new FormData();
        form.append("path", dest);
        if (index === 0) for (const dir of folders) form.append("dirs[]", dir);
        for (const item of part) {
          form.append("files[]", item.file, item.file.name);
          form.append("relpaths[]", item.rel);
        }
        const result = await this.sendUpload(form, token, (loaded) => {
          job.progress = Math.min(100, Math.round(((sent + loaded) / total) * 100));
        });
        sent += part.reduce((sum, item) => sum + item.file.size, 0);
        saved.push(...(result.saved || []), ...(result.folders || []));
        const failed = result.failed || [];
        for (const failure of failed.slice(0, 5)) window.toastFrontendError?.(`${failure.name}: ${failure.error}`, "Upload");
        if (failed.length > 5) window.toastFrontendError?.(`${failed.length - 5} more items failed.`, "Upload");
      }
      if (dest === this.path) {
        await this.refresh();
        // Select what landed here: uploaded files, or the uploaded top folders.
        const next = {};
        for (const entry of this.entries) {
          const lower = entry.path.toLowerCase();
          if (saved.some((p) => p.toLowerCase() === lower || p.toLowerCase().startsWith(lower + "\\"))) next[entry.path] = true;
        }
        this.selected = next;
      } else {
        window.toastFrontendSuccess?.(`Uploaded to ${dest.split("\\").pop()}`, "Upload", 3);
      }
    } catch (error) {
      window.toastFrontendError?.(error.message, "Upload");
      if (dest === this.path) this.refresh();
    } finally {
      this.uploads = this.uploads.filter((item) => item.id !== job.id);
    }
  },

  sendUpload(form, token, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/file_manager_upload");
      xhr.setRequestHeader("X-CSRF-Token", token);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded);
      };
      xhr.onload = () => {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error(xhr.status === 413 ? "The upload is too large." : `Upload failed (${xhr.status}).`));
        }
      };
      xhr.onerror = () => reject(new Error("The connection dropped during the upload."));
      xhr.send(form);
    });
  },

  // --- drag out (download) and drag to move -------------------------------------
  // Chromium (Chrome/Edge) turns a "DownloadURL" drag into a real download when
  // the item is dropped on the desktop or in File Explorer; other browsers ignore it.
  onRowDragStart(event, entry) {
    if (this.isPickerMode()) return event.preventDefault();
    if (!this.isSelected(entry)) this.selectOnly(entry.path);
    const items = this.selectedEntries;
    this.dragPaths = items.map((e) => e.path);
    const single = items.length === 1 && !items[0].is_dir;
    const name = single ? items[0].name : `${items.length === 1 ? items[0].name : "selection"}.zip`;
    const mime = single ? "application/octet-stream" : "application/zip";
    const url = new URL(this.downloadUrl(this.dragPaths), location.href).href;
    const dt = event.dataTransfer;
    dt.effectAllowed = "copyMove";
    dt.setData("DownloadURL", `${mime}:${name.replace(/:/g, "_")}:${url}`);
    dt.setData("text/plain", this.dragPaths.join("\n"));
  },

  onRowDragEnd() {
    this.dragPaths = null;
    this.dropTarget = "";
  },

  canDropOn(entry) {
    if (!entry?.is_dir || entry.outside) return false;
    if (!this.dragPaths) return true; // files from Windows: upload into this folder
    const target = entry.path.toLowerCase();
    return !this.dragPaths.some((p) => target === p.toLowerCase() || target.startsWith(p.toLowerCase() + "\\"));
  },

  onRowDragOver(event, entry) {
    if (!this.canDropOn(entry) || (!this.dragPaths && !this.isOsFileDrag(event))) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = this.dragPaths ? (event.ctrlKey ? "copy" : "move") : "copy";
    this.dropTarget = entry.path;
    this.dragOver = false;
  },

  onRowDrop(event, entry) {
    if (!this.canDropOn(entry)) return;
    event.preventDefault();
    event.stopPropagation();
    this.onDrop(event, entry.path);
  },

  async dropInternal(event, dest) {
    const paths = this.dragPaths || [];
    this.dragPaths = null;
    if (!paths.length || dest.toLowerCase() === this.path.toLowerCase()) return;
    const copy = event.ctrlKey;
    const result = await this.run(copy ? "Copy" : "Move", copy ? "copy" : "move", { paths, dest });
    if (result) {
      const count = result.created.length;
      window.toastFrontendSuccess?.(`${copy ? "Copied" : "Moved"} ${count} ${count === 1 ? "item" : "items"} to ${dest.split("\\").pop() || dest}`, "File Browser", 3);
    }
  },

  // --- keyboard -----------------------------------------------------------------
  onKeydown(event) {
    if (this.textEditor) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        this.saveText();
      } else if (event.key === "Escape") {
        this.closeTextEditor();
      }
      return;
    }
    const tag = event.target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || this.confirm) return;
    const key = event.key;
    const ctrl = event.ctrlKey || event.metaKey;
    const handled = () => event.preventDefault();
    if (key === "Escape") {
      if (this.menu) this.menu = null;
      else this.clearSelection();
    } else if (event.altKey && key === "ArrowLeft") { handled(); this.goBack(); }
    else if (event.altKey && key === "ArrowRight") { handled(); this.goForward(); }
    else if ((event.altKey && key === "ArrowUp") || key === "Backspace") { handled(); this.goUp(); }
    else if (key === "F5") { handled(); this.refresh(); }
    else if (key === "F2") { handled(); this.renameSelected(); }
    else if (key === "Delete") { handled(); this.requestDelete(event.shiftKey); }
    else if (key === "Enter") {
      handled();
      if (this.selectedEntries.length === 1) this.activate(this.selectedEntries[0]);
    } else if (ctrl && key.toLowerCase() === "a") { handled(); this.selectAll(); }
    else if (ctrl && key.toLowerCase() === "c") { handled(); this.copySelection(false); }
    else if (ctrl && key.toLowerCase() === "x") { handled(); this.copySelection(true); }
    else if (ctrl && key.toLowerCase() === "v") { handled(); this.paste(); }
    else if (ctrl && event.shiftKey && key.toLowerCase() === "n") { handled(); this.newFolder(); }
    else if ((ctrl && key.toLowerCase() === "l") || (event.altKey && key.toLowerCase() === "d")) { handled(); this.startAddressEdit(); }
    else if (key === "ArrowDown" || key === "ArrowUp" || key === "Home" || key === "End") {
      handled();
      this.moveFocus(key, event.shiftKey);
    } else if (key.length === 1 && !ctrl && !event.altKey) {
      this.typeAhead(key);
    }
  },

  // Closing a dialog hands focus to <body>. While the Files window is the top
  // modal, keys pressed with nothing focused still reach it (but never steal
  // a text selection's Ctrl+C or keys typed elsewhere).
  onWindowKeydown(event) {
    const root = document.querySelector(".fb");
    if (!root || event.defaultPrevented || root.contains(event.target)) return;
    if (event.target !== document.body && event.target !== document.documentElement) return;
    if (String(window.getSelection?.() || "")) return;
    const top = getModalStack().at(-1);
    if (!top || !String(top.path || "").includes("file-browser/file-browser.html")) return;
    this.onKeydown(event);
  },

  moveFocus(key, extend) {
    const list = this.visibleEntries;
    if (!list.length) return;
    let index = list.findIndex((e) => e.path === this.focusPath);
    if (key === "Home") index = 0;
    else if (key === "End") index = list.length - 1;
    else index = Math.max(0, Math.min(list.length - 1, index + (key === "ArrowDown" ? 1 : -1)));
    const entry = list[index];
    if (extend) this.clickEntry(entry, { shiftKey: true });
    else this.clickEntry(entry, {});
    this.scrollIntoView(entry.path);
  },

  typeAhead(char) {
    clearTimeout(this._typeAheadTimer);
    this._typeAhead += char.toLowerCase();
    this._typeAheadTimer = setTimeout(() => { this._typeAhead = ""; }, 800);
    const match = this.visibleEntries.find((e) => e.name.toLowerCase().startsWith(this._typeAhead));
    if (match) {
      this.clickEntry(match, {});
      this.scrollIntoView(match.path);
    }
  },

  // Keyboard shortcuts listen on .fb; give it focus back after dialogs close.
  focusList() {
    requestAnimationFrame(() => {
      const active = document.activeElement;
      if (active && ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName) && active.closest(".fb")) return;
      document.querySelector(".fb")?.focus({ preventScroll: true });
    });
  },

  scrollIntoView(path) {
    requestAnimationFrame(() => {
      const row = document.querySelector(`.fb-row[data-path="${CSS.escape(path)}"]`);
      row?.scrollIntoView({ block: "nearest" });
    });
  },

  // --- pickers -------------------------------------------------------------------
  configurePicker(options = {}) {
    const mode = [PICKER_TEXT_OPEN, PICKER_SAVE_AS].includes(options?.pickerMode) ? options.pickerMode : PICKER_NONE;
    this.pickerMode = mode;
    this.pickerConfirmLabel = options?.confirmLabel || (mode === PICKER_SAVE_AS ? "Save Here" : "Open Selected");
    this.pickerFilename = String(options?.filename || "").trim();
    const ext = String(options?.defaultExtension || extensionOf(this.pickerFilename) || "md").replace(/^\./, "").toLowerCase();
    this.pickerDefaultExtension = EDITOR_TEXT_EXTENSIONS.has(ext) ? ext : "md";
    this.pickerFilenameError = "";
    this.pickerOnConfirm = typeof options?.onConfirm === "function" ? options.onConfirm : null;
    if (mode) this.selected = {};
  },

  resetPicker() {
    this.configurePicker({});
  },

  isPickerMode() {
    return this.pickerMode !== PICKER_NONE;
  },

  isTextOpenPicker() {
    return this.pickerMode === PICKER_TEXT_OPEN;
  },

  isSaveAsPicker() {
    return this.pickerMode === PICKER_SAVE_AS;
  },

  pickerFilenameValue() {
    const raw = this.pickerFilename.trim();
    if (!raw) return "";
    return extensionOf(raw) ? raw : `${raw}.${this.pickerDefaultExtension}`;
  },

  pickerSelectedFiles() {
    return this.selectedEntries.filter((e) => this.isEditorText(e));
  },

  pickerSelectionLabel() {
    const count = this.pickerSelectedFiles().length;
    return count ? `${count} text ${count === 1 ? "file" : "files"} selected` : "Select .md or .txt files";
  },

  canConfirmPicker() {
    if (this.isTextOpenPicker()) return this.pickerSelectedFiles().length > 0;
    if (this.isSaveAsPicker()) return Boolean(this.pickerFilenameValue());
    return false;
  },

  async confirmPicker() {
    if (!this.isPickerMode() || this.isBulkBusy) return;
    let payload;
    if (this.isSaveAsPicker()) {
      const filename = this.pickerFilenameValue();
      if (!EDITOR_TEXT_EXTENSIONS.has(extensionOf(filename)) || /[<>:"/\\|?*]/.test(filename)) {
        this.pickerFilenameError = "Use a .md or .txt file name without < > : \" / \\ | ? *";
        return;
      }
      if (this.entries.some((e) => e.name.toLowerCase() === filename.toLowerCase())) {
        this.pickerFilenameError = `"${filename}" already exists here.`;
        return;
      }
      payload = { mode: this.pickerMode, directory: this.path, filename, path: joinPath(this.path, filename) };
    } else {
      payload = { mode: this.pickerMode, directory: this.path, selectedFiles: this.pickerSelectedFiles() };
    }
    this.isBulkBusy = true;
    try {
      const result = await this.pickerOnConfirm?.(payload);
      if (result !== false) window.closeModal(MODAL_PATH);
    } catch (error) {
      this.pickerFilenameError = error?.message || "That didn't work.";
    } finally {
      this.isBulkBusy = false;
    }
  },

  cancelPicker() {
    window.closeModal(MODAL_PATH);
  },
};

export const store = createStore("fileBrowser", model);

// Chat messages link file paths; folders open here, files download.
window.openFileLink = async function (path) {
  try {
    const result = await callJsonApi("file_manager", { action: "locate", path });
    if (!result?.ok) throw new Error(result?.error || "Not available");
    if (result.select) store.downloadFile({ path: result.select, name: result.select.split("\\").pop() });
    else await store.open(result.folder);
  } catch (error) {
    window.toastFrontendError?.(error.message || "Could not open the file", "File Browser");
  }
};
