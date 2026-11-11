export default async function registerChildAgentsSurface(surfaces) {
  surfaces.registerSurface({
    id: "child-agents",
    title: "Child agents",
    icon: "account_tree",
    order: 23,
    modalPath: "/plugins/_child_agents/webui/main.html",
  });
}
