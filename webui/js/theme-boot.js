// Applies the saved accent color and material before first paint, so the
// page never flashes the default theme. Loaded as a classic (blocking)
// script in index.html's <head>; preferences-store.js owns changes after
// startup and writes the same localStorage keys.
(() => {
  const root = document.documentElement;
  let accent = "#4a8cff";
  let material = "glass";
  try {
    const savedAccent = localStorage.getItem("accentColor");
    const savedMaterial = localStorage.getItem("materialStyle");
    if (/^#[0-9a-fA-F]{6}$/.test(savedAccent || "")) accent = savedAccent;
    if (["solid", "glass", "enhanced"].includes(savedMaterial)) material = savedMaterial;
  } catch {
    // Storage blocked (private window): defaults are fine.
  }
  root.style.setProperty("--accent", accent);
  root.dataset.material = material;
})();
