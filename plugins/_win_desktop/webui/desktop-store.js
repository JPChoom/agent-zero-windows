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

  let streaming = false;

  const setStatus = (text, warn = false) => {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle("wd-warn", warn);
  };

  function start() {
    // Cache-busted so a reconnect is not served the previous response.
    frame.src = `${STREAM_URL}?t=${Date.now()}`;
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

  stop();
  return true;
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
