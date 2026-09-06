/**
 * Behaviour for the Windows Desktop viewer panel.
 *
 * Lives in a module rather than a <script> inside desktop-panel.html because
 * that file is injected with innerHTML by <x-component>, and scripts inserted
 * that way never execute. The surface registration imports this and calls
 * mount() once the panel is in the DOM - the same shape _desktop uses.
 */

const STREAM_URL = "/api/plugins/_win_desktop/desktop_stream";
const INPUT_URL = "/plugins/_win_desktop/desktop_input";

const NAMED_KEYS = {
  Enter: "enter", Backspace: "backspace", Tab: "tab", Escape: "esc",
  Delete: "delete", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left",
  ArrowRight: "right", Home: "home", End: "end", PageUp: "pageup",
  PageDown: "pagedown",
};

export function mount(scope = document) {
  const pick = (name) => scope.querySelector(`[data-wd="${name}"]`);
  const frame = pick("frame");
  if (!frame || frame.dataset.wdInit === "1") return false;
  frame.dataset.wdInit = "1";

  const stage = pick("stage");
  const status = pick("status");
  const toggle = pick("toggle");
  const control = pick("control");
  const hint = pick("hint");
  const monitorSelect = pick("monitor");
  const fullscreenButton = pick("fullscreen");
  const expandButton = pick("expand");
  const root = frame.closest(".wd-root");

  let streaming = false;
  const currentMonitor = () => monitorSelect?.value || "all";

  const setStatus = (text, warn = false) => {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle("wd-warn", warn);
  };

  function start() {
    // Cache-busted so a reconnect is not served the previous response.
    const monitor = encodeURIComponent(currentMonitor());
    frame.src = `${STREAM_URL}?monitor=${monitor}&t=${Date.now()}`;
    streaming = true;
    if (toggle) toggle.textContent = "Stop";
    setStatus("connecting…");
  }

  function stop() {
    streaming = false;
    frame.removeAttribute("src");
    if (toggle) toggle.textContent = "Start";
    setStatus("stopped");
  }

  toggle?.addEventListener("click", () => (streaming ? stop() : start()));
  frame.addEventListener("load", () => streaming && setStatus("live"));
  frame.addEventListener("error", () => {
    if (!streaming) return;
    setStatus("stream ended — reconnecting", true);
    // The endpoint bounds each stream so an abandoned tab cannot hold a
    // worker thread forever; reconnecting keeps a watched panel continuous.
    setTimeout(() => streaming && start(), 1000);
  });

  control?.addEventListener("change", () => {
    stage?.classList.toggle("wd-live", control.checked);
    if (hint) {
      hint.textContent = control.checked
        ? "Live: clicks, scrolling and typing go to the real desktop."
        : "Read-only. Tick the box above to send clicks and typing to the real desktop.";
    }
  });

  async function send(payload) {
    if (!control?.checked) return;
    try {
      const response = await globalThis.fetchApi(INPUT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!data.ok) setStatus(data.error || "input rejected", true);
    } catch (error) {
      setStatus(String(error), true);
    }
  }

  // The frame is letterboxed inside the stage, so a click must be measured
  // against the image's own box and sent with that box's size - the server
  // scales it back to real screen pixels from those dimensions.
  function framePoint(event) {
    const box = frame.getBoundingClientRect();
    if (!box.width || !box.height) return null;
    return {
      x: event.clientX - box.left,
      y: event.clientY - box.top,
      frame_width: box.width,
      frame_height: box.height,
      // The server crops to this monitor, so it also needs to know which one
      // in order to add the right offset back - without it every click would
      // land on the leftmost screen.
      monitor: currentMonitor(),
    };
  }

  frame.addEventListener("click", (event) => {
    const point = framePoint(event);
    if (point) send({ action: "click", ...point });
  });

  frame.addEventListener("contextmenu", (event) => {
    if (!control?.checked) return;
    event.preventDefault();
    const point = framePoint(event);
    if (point) send({ action: "click", button: "right", ...point });
  });

  frame.addEventListener("wheel", (event) => {
    if (!control?.checked) return;
    event.preventDefault();
    const point = framePoint(event);
    if (point) send({ action: "scroll", amount: event.deltaY > 0 ? -1 : 1, ...point });
  }, { passive: false });

  stage?.setAttribute("tabindex", "0");
  stage?.addEventListener("keydown", (event) => {
    if (!control?.checked) return;
    event.preventDefault();
    const modifiers = [];
    if (event.ctrlKey) modifiers.push("ctrl");
    if (event.altKey) modifiers.push("alt");
    if (event.shiftKey) modifiers.push("shift");
    // A plain printable character is typed literally; anything with a
    // modifier or a named key is sent as a combination for the server to
    // map to virtual-key codes.
    if (event.key.length === 1 && !modifiers.length) {
      send({ action: "type", text: event.key });
      return;
    }
    const key = NAMED_KEYS[event.key] || (event.key.length === 1 ? event.key : null);
    if (!key) return;
    send({ action: "key", keys: [...modifiers, key].join("+") });
  });

  // Switching screens restarts the stream, since the crop is chosen server
  // side per connection rather than per frame.
  monitorSelect?.addEventListener("change", () => {
    if (streaming) start();
  });

  // Where the panel normally lives, so expanding can put it back.
  let homeParent = null;
  let homeNextSibling = null;

  function setExpanded(on) {
    if (!root) return;
    if (on && !root.classList.contains("wd-expanded")) {
      // The right canvas sets `transform` (an identity matrix, for its slide
      // animation), which makes it the containing block for any fixed-
      // position descendant - so `inset: 0` would fill the panel rather than
      // the window. Re-parenting to <body> is what actually escapes it;
      // CSS alone cannot.
      homeParent = root.parentElement;
      homeNextSibling = root.nextSibling;
      document.body.appendChild(root);
    } else if (!on && homeParent) {
      homeParent.insertBefore(root, homeNextSibling);
      homeParent = null;
      homeNextSibling = null;
    }
    root.classList.toggle("wd-expanded", on);
    if (on) stage?.focus();
  }

  expandButton?.addEventListener("click", () => {
    setExpanded(!root?.classList.contains("wd-expanded"));
  });

  fullscreenButton?.addEventListener("click", async () => {
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => {});
      return;
    }
    try {
      await stage.requestFullscreen();
      // Keyboard events are bound to the stage, so it must hold focus or
      // typing in fullscreen would go nowhere.
      stage.focus();
    } catch (error) {
      // Some embedded browsers refuse the Fullscreen API outright. Falling
      // back to the CSS mode means the button still does something useful
      // rather than reporting a failure the user cannot act on.
      setExpanded(true);
      setStatus("filled the window (true fullscreen blocked here)");
    }
  });

  // Esc leaves the CSS mode too, matching what it does for real fullscreen.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root?.classList.contains("wd-expanded")) {
      setExpanded(false);
    }
  });

  populateMonitors(monitorSelect);
  stop();
  return true;
}

/** Fill the screen selector from the server's monitor list. */
async function populateMonitors(select) {
  if (!select) return;
  try {
    const response = await fetch(`${STREAM_URL}?monitors=1`);
    if (!response.ok) return;
    const { monitors } = await response.json();
    if (!Array.isArray(monitors) || monitors.length < 2) return;
    for (const monitor of monitors) {
      const option = document.createElement("option");
      option.value = String(monitor.index);
      // Positional labels: Windows' enumeration order is not left to right,
      // so an index alone would not tell the user which screen it is.
      option.textContent =
        `Screen ${monitor.index + 1}` +
        (monitor.primary ? " (main)" : "") +
        ` – ${monitor.width}×${monitor.height}`;
      select.appendChild(option);
    }
  } catch {
    // Selector stays at "All screens"; not worth surfacing.
  }
}

/** Retry until <x-component> has injected the panel markup. */
export async function mountWhenReady(timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (mount()) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return false;
}

/**
 * Mount whenever the panel markup appears, for as long as the page lives.
 *
 * Depending on the surface's open() hook proved unreliable: the panel wired
 * on one run and not the next, because whether the markup exists when that
 * hook fires is a race with <x-component>'s injection. Observing the DOM
 * removes the timing question entirely and also re-wires a panel that is
 * unmounted and remounted, or opened in the modal after the docked canvas.
 * mount() is idempotent per frame element, so repeated calls are free.
 */
let observing = false;

export function autoMount() {
  mount();
  if (observing) return;
  observing = true;
  new MutationObserver(() => mount()).observe(document.body, {
    childList: true,
    subtree: true,
  });
}
