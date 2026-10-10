export default async function registerWorkspaceSurface(surfaces) {
  surfaces.registerSurface({
    id: "workspace",
    title: "Workspace",
    icon: "lan",
    order: 22,
    modalPath: "/plugins/_workspace/webui/main.html",
  });
}
