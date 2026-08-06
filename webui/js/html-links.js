export function addBlankTargetsToLinks(str) {
  const doc = new DOMParser().parseFromString(str, "text/html");

  doc.querySelectorAll("a").forEach((anchor) => {
    const href = anchor.getAttribute("href") || "";
    if (
      href.startsWith("#") ||
      href.trim().toLowerCase().startsWith("javascript")
    ) {
      return;
    }

    if (
      !anchor.hasAttribute("target") ||
      anchor.getAttribute("target") === ""
    ) {
      anchor.setAttribute("target", "_blank");
    }

    const rel = (anchor.getAttribute("rel") || "").split(/\s+/).filter(Boolean);
    if (!rel.includes("noopener")) rel.push("noopener");
    if (!rel.includes("noreferrer")) rel.push("noreferrer");
    anchor.setAttribute("rel", rel.join(" "));
  });

  return doc.body.innerHTML;
}
