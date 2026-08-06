import { callJsonApi } from "/js/api.js";
import { isModalOpen } from "/js/modals.js";

const DEFAULT_SURFACE = "welcome";
const STARTUP_DELAY_MS = 650;
const SUPPRESSION_PREFIX = "discovery_auto_modal_closed";

let initialized = false;
let lastOpened = null;
let checking = false;

function cleanPath(path = "") {
  return String(path || "").replace(/^\/+/, "");
}

function currentContextId(fallback = "") {
  try {
    return fallback || globalThis.getContext?.() || sessionStorage.getItem("lastSelectedChat") || "welcome";
  } catch {
    return fallback || "welcome";
  }
}

function bannerSupportsSurface(banner, surface) {
  const surfaces = banner?.auto_modal_surfaces;
  return !Array.isArray(surfaces) || surfaces.length === 0 || surfaces.includes(surface);
}

function suppressionKey({ surface, ctxid, reason, path }) {
  return `${SUPPRESSION_PREFIX}:${surface}:${ctxid || "none"}:${reason || "unknown"}:${cleanPath(path)}`;
}

function isSuppressed(item) {
  try {
    return sessionStorage.getItem(suppressionKey(item)) === "1";
  } catch {
    return false;
  }
}

function suppress(item) {
  try {
    sessionStorage.setItem(suppressionKey(item), "1");
  } catch {
    // no-op
  }
}

function modalAlreadyOpen(path) {
  return isModalOpen(path);
}

async function fetchAutoModalBanner(surface, ctxid) {
  const response = await callJsonApi("/banners", {
    banners: [],
    context: {
      is_welcome: surface === "welcome",
      is_onboarding: document.body.dataset.mode === "onboarding",
      surface,
      ctxid,
    },
  });

  const banners = Array.isArray(response?.banners) ? response.banners : [];
  return banners
    .filter((banner) => banner?.auto_modal_path)
    .filter((banner) => bannerSupportsSurface(banner, surface))
    .sort((left, right) => (Number(right.auto_modal_priority || 0) - Number(left.auto_modal_priority || 0)))[0] || null;
}

async function maybeOpenAutoModal(surface = DEFAULT_SURFACE, detail = {}) {
  if (checking) return;
  checking = true;
  const ctxid = currentContextId(detail.ctxid || "");

  try {
    const banner = await fetchAutoModalBanner(surface, ctxid);
    if (!banner?.auto_modal_path) return;

    const item = {
      surface,
      ctxid,
      path: banner.auto_modal_path,
      reason: banner.auto_modal_reason || banner.id || "auto-modal",
    };

    if (isSuppressed(item) || modalAlreadyOpen(item.path)) return;

    const opener = globalThis.ensureModalOpen || globalThis.openModal;
    if (!opener) return;

    lastOpened = item;
    await opener(item.path);
  } catch (error) {
    console.error("Discovery auto-modal check failed:", error);
  } finally {
    checking = false;
  }
}

function handleModalClosed(event) {
  const closedPath = event?.detail?.modalPath || "";
  if (lastOpened && cleanPath(closedPath) === cleanPath(lastOpened.path)) {
    suppress(lastOpened);
    const surface = lastOpened.surface;
    const ctxid = lastOpened.ctxid;
    lastOpened = null;
    window.setTimeout(() => {
      void maybeOpenAutoModal(surface, { ctxid });
    }, 250);
    return;
  }

  window.setTimeout(() => {
    void maybeOpenAutoModal(DEFAULT_SURFACE);
  }, 250);
}

function handleChatCreated(event) {
  const ctxid = event?.detail?.ctxid || "";
  window.setTimeout(() => {
    void maybeOpenAutoModal("chat-created", { ctxid });
  }, 300);
}

export default function initDiscoveryAutoModal() {
  if (initialized) return;
  initialized = true;

  document.addEventListener("modal-closed", handleModalClosed);
  document.addEventListener("chat-created", handleChatCreated);

  window.setTimeout(() => {
    void maybeOpenAutoModal(DEFAULT_SURFACE);
  }, STARTUP_DELAY_MS);
}
