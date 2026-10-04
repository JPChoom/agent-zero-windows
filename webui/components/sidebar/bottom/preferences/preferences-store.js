import { createStore } from "/js/AlpineStore.js";
import * as css from "/js/css.js";
import { ttsService } from "/js/tts-service.js";
import { applyModeSteps } from "/components/messages/process-group/process-group-dom.js";
import { store as colorPickerStore } from "/components/color-picker/color-picker-store.js";

// Wallpaper images are stored in IndexedDB, not localStorage - a photo can
// easily be several MB, well past what localStorage can hold (and it's
// synchronous, so a multi-MB read/write would block the main thread).
const WALLPAPER_DB = "a0-wallpaper-db";
const WALLPAPER_STORE = "wallpaper";
const WALLPAPER_KEY = "current";

// Keep in sync with js/theme-boot.js (same keys and validation).
const DEFAULT_ACCENT = "#4a8cff";
const MATERIALS = ["solid", "glass", "enhanced"];
const isHexColor = (value) => /^#[0-9a-fA-F]{6}$/.test(value || "");

function openWallpaperDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(WALLPAPER_DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(WALLPAPER_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function saveWallpaperBlob(blob) {
  const db = await openWallpaperDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(WALLPAPER_STORE, "readwrite");
    tx.objectStore(WALLPAPER_STORE).put(blob, WALLPAPER_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function loadWallpaperBlob() {
  const db = await openWallpaperDb();
  return new Promise((resolve, reject) => {
    const req = db.transaction(WALLPAPER_STORE, "readonly").objectStore(WALLPAPER_STORE).get(WALLPAPER_KEY);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
  });
}

async function deleteWallpaperBlob() {
  const db = await openWallpaperDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(WALLPAPER_STORE, "readwrite");
    tx.objectStore(WALLPAPER_STORE).delete(WALLPAPER_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

// Preferences store centralizes user preference toggles and side-effects
const model = {
  // UI toggles (initialized with safe defaults, loaded from localStorage in init)
  get autoScroll() {
    return this._autoScroll;
  },
  set autoScroll(value) {
    this._autoScroll = value;
    this._applyAutoScroll(value);
  },
  _autoScroll: true,

  get darkMode() {
    return this._darkMode;
  },
  set darkMode(value) {
    this._darkMode = value;
    this._applyDarkMode(value);
  },
  _darkMode: true,

  // Accent color (css/theme.css --accent): drives interactive highlights
  // and the backdrop glow. Status colors (ok/warn/error) stay semantic.
  // js/theme-boot.js applies the saved value before first paint.
  get accentColor() {
    return this._accentColor;
  },
  set accentColor(value) {
    this._applyAccentColor(value);
  },
  _accentColor: DEFAULT_ACCENT,

  // Opens the themed picker ($store.colorPicker) for a custom accent.
  pickAccent(anchor) {
    colorPickerStore.open(anchor, {
      title: "Accent",
      value: this._accentColor,
      swatches: this.accentOptions.map((opt) => opt.value),
      onChange: (hex) => {
        this.accentColor = hex;
      },
    });
  },

  accentOptions: [
    { name: "Blue", value: "#4a8cff" },
    { name: "Violet", value: "#8b6cff" },
    { name: "Pink", value: "#e8559f" },
    { name: "Red", value: "#ef5f5a" },
    { name: "Orange", value: "#f0954b" },
    { name: "Green", value: "#3fc27a" },
    { name: "Teal", value: "#1fb3b0" },
  ],

  // Material (css/theme.css --mat-*): how much glass floating surfaces
  // (composer, menus, modals) use. Solid = no transparency or blur.
  get materialStyle() {
    return this._materialStyle;
  },
  set materialStyle(value) {
    this._applyMaterialStyle(value);
  },
  _materialStyle: "glass",

  materialOptions: [
    { id: "solid", label: "Solid", title: "No transparency or blur - fastest" },
    { id: "glass", label: "Glass", title: "Translucent floating surfaces" },
    { id: "enhanced", label: "Enhanced", title: "Stronger glass with accent edges" },
  ],

  // Wallpaper: an uploaded image or looping video (mp4/webm) used as the
  // backdrop instead of the gradient. The blob itself lives in IndexedDB
  // (see helpers above); hasWallpaper/wallpaperFit are the only parts small
  // enough for localStorage. Images paint body::before (--backdrop-image);
  // videos play in a muted, looping <video class="wallpaper-video"> fixed
  // behind the UI (see _applyWallpaperBlob).
  get hasWallpaper() {
    return this._hasWallpaper;
  },
  _hasWallpaper: false,

  get wallpaperFit() {
    return this._wallpaperFit;
  },
  set wallpaperFit(value) {
    this._wallpaperFit = value;
    localStorage.setItem("wallpaperFit", value);
    this._applyWallpaperFit(value);
  },
  _wallpaperFit: "fill",

  wallpaperFitOptions: [
    { id: "fill", label: "Fill", title: "Crop to fill the screen, keeping proportions" },
    { id: "fit", label: "Fit", title: "Show the whole image, letterboxed if needed" },
    { id: "stretch", label: "Stretch", title: "Stretch to exactly fill the screen" },
    { id: "tile", label: "Tile", title: "Repeat the image at its original size (videos fill)" },
    { id: "center", label: "Center", title: "Original size, centered" },
  ],

  _wallpaperObjectUrl: null,
  _wallpaperVisibilityHandler: null,

  async setWallpaperFile(file) {
    if (!file || !(file.type?.startsWith("image/") || file.type?.startsWith("video/"))) return;
    try {
      await saveWallpaperBlob(file);
      this._applyWallpaperBlob(file);
      this._hasWallpaper = true;
      localStorage.setItem("hasWallpaper", "true");
    } catch (error) {
      console.error("Failed to save wallpaper", error);
      globalThis.toastFrontendError?.("Could not save wallpaper (the file may be too large for browser storage)", "Preferences");
    }
  },

  async clearWallpaper() {
    this._hasWallpaper = false;
    localStorage.setItem("hasWallpaper", "false");
    if (this._wallpaperObjectUrl) {
      URL.revokeObjectURL(this._wallpaperObjectUrl);
      this._wallpaperObjectUrl = null;
    }
    document.body.classList.remove("has-wallpaper");
    document.documentElement.style.removeProperty("--backdrop-image");
    this._removeWallpaperVideo();
    try {
      await deleteWallpaperBlob();
    } catch (error) {
      console.error("Failed to delete wallpaper", error);
    }
  },

  _applyWallpaperBlob(blob) {
    if (this._wallpaperObjectUrl) URL.revokeObjectURL(this._wallpaperObjectUrl);
    this._wallpaperObjectUrl = URL.createObjectURL(blob);
    const root = document.documentElement;
    if (blob.type?.startsWith("video/")) {
      root.style.removeProperty("--backdrop-image");
      const video = this._ensureWallpaperVideo();
      video.src = this._wallpaperObjectUrl;
      this._applyWallpaperFit(this._wallpaperFit);
      this._syncWallpaperVideoPlayback();
    } else {
      this._removeWallpaperVideo();
      root.style.setProperty("--backdrop-image", `url("${this._wallpaperObjectUrl}")`);
    }
    document.body.classList.add("has-wallpaper");
  },

  _applyWallpaperFit(value) {
    const bySize = { fill: "cover", fit: "contain", stretch: "100% 100%", tile: "auto", center: "auto" };
    const byRepeat = { tile: "repeat" };
    document.documentElement.style.setProperty("--backdrop-image-size", bySize[value] || "cover");
    document.documentElement.style.setProperty("--backdrop-image-repeat", byRepeat[value] || "no-repeat");
    // A video cannot tile; it fills instead.
    const byObjectFit = { fill: "cover", fit: "contain", stretch: "fill", tile: "cover", center: "none" };
    const video = document.querySelector("video.wallpaper-video");
    if (video) video.style.objectFit = byObjectFit[value] || "cover";
  },

  // The video sits fixed behind everything (z-index -1, after body::before
  // in tree order, so it covers the gradient). Muted + playsinline are
  // required for autoplay; it never takes pointer events or focus.
  _ensureWallpaperVideo() {
    let video = document.querySelector("video.wallpaper-video");
    if (video) return video;
    video = document.createElement("video");
    video.className = "wallpaper-video";
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    video.setAttribute("aria-hidden", "true");
    video.tabIndex = -1;
    video.style.cssText =
      "position:fixed;inset:0;width:100%;height:100%;z-index:-1;pointer-events:none;object-fit:cover;";
    document.body.prepend(video);
    if (!this._wallpaperVisibilityHandler) {
      this._wallpaperVisibilityHandler = () => this._syncWallpaperVideoPlayback();
      document.addEventListener("visibilitychange", this._wallpaperVisibilityHandler);
    }
    return video;
  },

  // Play only while the tab is visible and the user has not asked the OS
  // for reduced motion (then the first frame stays as a still wallpaper).
  _syncWallpaperVideoPlayback() {
    const video = document.querySelector("video.wallpaper-video");
    if (!video) return;
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (document.hidden || reduced) video.pause();
    else video.play().catch(() => {});
  },

  _removeWallpaperVideo() {
    const video = document.querySelector("video.wallpaper-video");
    if (!video) return;
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.remove();
  },

  get speech() {
    return this._speech;
  },
  set speech(value) {
    this._speech = value;
    this._applySpeech(value);
  },
  _speech: false,

  get showUtils() {
    return this._showUtils;
  },
  set showUtils(value) {
    this._showUtils = value;
    this._applyShowUtils(value);
  },
  _showUtils: false,

  // Chat container width preference for HiDPI/large screens
  get chatWidth() {
    return this._chatWidth;
  },
  set chatWidth(value) {
    this._chatWidth = value;
    this._applyChatWidth(value);
  },
  _chatWidth: "55", // Default width in em (standard)

  // Width presets: { label, value in em }
  chatWidthOptions: [
    { label: "MIN", value: "40" },
    { label: "WIDE", value: "55" },
    { label: "2X", value: "80" },
    { label: "FULL", value: "full" },
  ],

  // Detail mode for process groups/steps expansion
  get detailMode() {
    return this._detailMode;
  },
  set detailMode(value) {
    this._detailMode = value;
    this._applyDetailMode(value);
  },
  _detailMode: "current", // Default: show current step only

  // Detail mode options for UI sidebar
  detailModeOptions: [
    { label: "NO", value: "collapsed", title: "All collapsed" },
    { label: "LIST", value: "list", title: "Steps collapsed" },
    { label: "STEP", value: "current", title: "Current step only" },
    { label: "ALL", value: "expanded", title: "All expanded" },
  ],

  // Initialize preferences and apply current state
  init() {
    try {
      // Load persisted preferences with safe fallbacks
      try {
        const storedDarkMode = localStorage.getItem("darkMode");
        this._darkMode = storedDarkMode !== "false";
      } catch {
        this._darkMode = true; // Default to dark mode if localStorage is unavailable
      }

      try {
        const storedSpeech = localStorage.getItem("speech");
        this._speech = storedSpeech === "true";
      } catch {
        this._speech = false; // Default to speech off if localStorage is unavailable
      }

      // Load chat width preference
      try {
        const storedChatWidth = localStorage.getItem("chatWidth");
        if (storedChatWidth && this.chatWidthOptions.some(opt => opt.value === storedChatWidth)) {
          this._chatWidth = storedChatWidth;
        }
      } catch {
        this._chatWidth = "55"; // Default to standard
      }

      // Load detail mode preference
      try {
        const storedDetailMode = localStorage.getItem("detailMode");
        if (storedDetailMode && this.detailModeOptions.some(opt => opt.value === storedDetailMode)) {
          this._detailMode = storedDetailMode;
        }
      } catch {
        this._detailMode = "current"; // Default
      }

      // Load accent + material (theme-boot.js already applied them before
      // first paint; this just syncs the store).
      try {
        const storedAccent = localStorage.getItem("accentColor");
        if (isHexColor(storedAccent)) this._accentColor = storedAccent.toLowerCase();
        const storedMaterial = localStorage.getItem("materialStyle");
        if (MATERIALS.includes(storedMaterial)) this._materialStyle = storedMaterial;
      } catch {
        // storage unavailable: keep defaults
      }

      // Load wallpaper fit-mode preference
      try {
        const storedFit = localStorage.getItem("wallpaperFit");
        if (storedFit && this.wallpaperFitOptions.some(opt => opt.id === storedFit)) {
          this._wallpaperFit = storedFit;
        }
      } catch {
        this._wallpaperFit = "fill";
      }

      // Load wallpaper flag; the actual image blob is fetched from
      // IndexedDB below since that read is async (init() itself isn't).
      try {
        this._hasWallpaper = localStorage.getItem("hasWallpaper") === "true";
      } catch {
        this._hasWallpaper = false;
      }

      // load utility messages preference
      try{
        const storedShowUtils = localStorage.getItem("showUtils");
        this._showUtils = storedShowUtils === "true";
      } catch {
        this._showUtils = false; // Default to speech off if localStorage is unavailable
      }

      // Apply all preferences
      this._applyDarkMode(this._darkMode);
      this._applyAccentColor(this._accentColor);
      this._applyMaterialStyle(this._materialStyle);
      this._applyWallpaperFit(this._wallpaperFit);
      this._applyAutoScroll(this._autoScroll);
      this._applySpeech(this._speech);
      this._applyShowUtils(this._showUtils);
      this._applyChatWidth(this._chatWidth);
      this._applyDetailMode(this._detailMode);

      // Restore the wallpaper image itself (async - IndexedDB has no sync
      // API). If the flag says a wallpaper should be active but the blob
      // is somehow missing, fall back cleanly to the gradient instead of
      // leaving a permanently-stuck "has wallpaper" state.
      if (this._hasWallpaper) {
        loadWallpaperBlob()
          .then((blob) => {
            if (blob) {
              this._applyWallpaperBlob(blob);
            } else {
              this.clearWallpaper();
            }
          })
          .catch((error) => {
            console.error("Failed to restore wallpaper", error);
            this.clearWallpaper();
          });
      }
    } catch (e) {
      console.error("Failed to initialize preferences store", e);
    }
  },

  _applyAutoScroll(value) {
    // nothing for now
  },

  _applyDarkMode(value) {
    if (value) {
      document.body.classList.remove("light-mode");
      document.body.classList.add("dark-mode");
    } else {
      document.body.classList.remove("dark-mode");
      document.body.classList.add("light-mode");
    }
    localStorage.setItem("darkMode", value);
  },

  _applyAccentColor(value) {
    const accent = isHexColor(value) ? value.toLowerCase() : DEFAULT_ACCENT;
    this._accentColor = accent;
    document.documentElement.style.setProperty("--accent", accent);
    try { localStorage.setItem("accentColor", accent); } catch {}
  },

  _applyMaterialStyle(value) {
    const material = MATERIALS.includes(value) ? value : "glass";
    this._materialStyle = material;
    document.documentElement.dataset.material = material;
    try { localStorage.setItem("materialStyle", material); } catch {}
  },

  _applySpeech(value) {
    localStorage.setItem("speech", value);
    if (!value) ttsService.stop();
  },


  _applyShowUtils(value) {
    localStorage.setItem("showUtils", value);
    css.toggleCssProperty(
      ".process-step.message-util",
      "display",
      value ? undefined : "none"
    );
  },

  _applyChatWidth(value) {
    localStorage.setItem("chatWidth", value);
    // Set CSS custom property for chat max-width
    const root = document.documentElement;
    if (value === "full") {
      root.style.setProperty("--chat-max-width", "100%");
    } else {
      root.style.setProperty("--chat-max-width", `${value}em`);
    }
  },

  _applyDetailMode(value) {
    localStorage.setItem("detailMode", value);
    // Apply mode to all existing DOM elements
    applyModeSteps(this._detailMode, this._showUtils);
  },
};

export const store = createStore("preferences", model);
