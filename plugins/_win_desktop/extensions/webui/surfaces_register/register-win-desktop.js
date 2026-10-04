import { autoMount } from "/plugins/_win_desktop/webui/desktop-store.js";

// Wired by a DOM observer rather than only from open(): whether the panel
// markup exists when that hook fires is a race with <x-component>, and it
// was observed wiring on one run and not the next.
autoMount();

export default async function registerWindowsDesktopSurface(surfaces) {
  surfaces.registerSurface({
    id: "win-desktop",
    title: "Desktop",
    icon: "desktop_windows",
    order: 21,
    modalPath: "/plugins/_win_desktop/webui/main.html",
    async open() {
      autoMount();
    },
  });
}
