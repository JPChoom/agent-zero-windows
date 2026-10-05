export default async function registerCalendarSurface(surfaces) {
  surfaces.registerSurface({
    id: "calendar",
    title: "Calendar",
    icon: "calendar_month",
    order: 40,
    modalPath: "/plugins/_calendar/webui/main.html",
    async open(payload = {}) {
      const { store } = await import("/plugins/_calendar/webui/calendar-store.js");
      await store.onOpen?.(payload);
    },
  });
}
