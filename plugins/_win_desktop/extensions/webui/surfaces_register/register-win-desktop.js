import { mountWhenReady } from "/plugins/_win_desktop/webui/desktop-store.js";

export default async function registerWindowsDesktopSurface(surfaces) {
  surfaces.registerSurface({
    id: "win-desktop",
    title: "Windows Desktop",
    icon: "desktop_windows",
    order: 21,
    modalPath: "/plugins/_win_desktop/webui/main.html",
    // The panel markup is injected by <x-component> after the surface opens,
    // so wiring has to wait for it rather than run at registration time.
    async open() {
      await mountWhenReady();
    },
  });
}
