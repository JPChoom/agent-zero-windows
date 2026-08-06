export default function refreshTimeTravelOnContextChange(ctx) {
  const store = globalThis.Alpine?.store?.("timeTravel");
  const modalOpen = globalThis.isModalOpen?.("/plugins/_time_travel/webui/main.html")
    || globalThis.isModalOpen?.("plugins/_time_travel/webui/main.html");
  if (!store || !modalOpen) return;
  const nextContextId = String(ctx?.snapshot?.context || "");
  if (nextContextId && nextContextId !== store.contextId) {
    store.scheduleRefresh({ contextId: nextContextId, reason: "context-change" });
  }
}
