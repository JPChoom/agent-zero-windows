import { drawProcessStep } from "/js/messages.js";
import { callJsonApi } from "/js/api.js";
import { store as approvalPopup } from "/plugins/_safety_policy/webui/approval-popup-store.js";

export default async function registerApprovalHandler(extData) {
  if (extData?.type === "safety_policy_approval_request") {
    extData.handler = drawMessageApprovalRequest;
  }
}

function drawMessageApprovalRequest({
  id,
  heading,
  content,
  kvps,
  ...additional
}) {
  const approvalId = kvps?.approval_id || "";
  const resolved = Boolean(kvps?.resolved);
  const outcome = kvps?.outcome || "";
  const category = kvps?.category || "";
  const command = String(kvps?.command || "");
  const host = String(kvps?.remember_host || "");
  const expiresAt = Number(kvps?.expires_at) || 0;

  const title = resolved
    ? `Safety policy: ${outcomeLabel(outcome)} (${category})`
    : `Safety policy: approval required (${category})`;

  if (approvalId) {
    if (resolved) {
      approvalPopup.onResolved(approvalId);
    } else {
      // Pops a modal so a held command gets noticed even when the chat is
      // scrolled away; the buttons below stay as the fallback.
      approvalPopup.offer({ approvalId, category, command, host, content, expiresAt });
    }
  }

  const actionButtons = [];
  if (!resolved && approvalId) {
    const respond = async (approved, remember = false) => {
      const result = await callJsonApi("safety_policy_approve", {
        approval_id: approvalId,
        approved,
        remember,
      });
      if (result?.error) {
        window.toastFrontendError?.(result.error, "Safety Policy");
      }
      approvalPopup.onResolved(approvalId);
    };

    actionButtons.push(createDecisionButton("Allow once", "approve-btn", () => respond(true)));
    if (host) {
      actionButtons.push(
        createDecisionButton(`Always allow ${host}`, "approve-btn", () => respond(true, true)),
      );
    }
    actionButtons.push(createDecisionButton("Deny", "deny-btn", () => respond(false)));
  }

  return drawProcessStep({
    id,
    title,
    code: "APR",
    classes: ["safety-policy-approval-step"],
    kvps: null,
    content: command ? `${content || ""}\n\n${command}`.trim() : content,
    contentClasses: ["terminal-output"],
    actionButtons,
    log: { type: "safety_policy_approval_request", timestamp: additional?.timestamp, agentno: additional?.agentno || 0 },
  });
}

function outcomeLabel(outcome) {
  switch (outcome) {
    case "approved":
      return "approved";
    case "denied":
      return "denied";
    case "timeout":
      return "timed out (denied)";
    default:
      return outcome || "resolved";
  }
}

function createDecisionButton(label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `action-button safety-policy-decision-btn ${className}`;
  button.textContent = label;
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    // Disable the whole row: a second click would resolve an already
    // settled future and read as a no-op the user cannot explain.
    const row = button.parentElement;
    const buttons = [...(row ? row.querySelectorAll("button") : [button])];
    buttons.forEach((b) => (b.disabled = true));
    try {
      await handler();
    } catch (error) {
      window.toastFrontendError?.(error?.message || "Failed to submit decision", "Safety Policy");
      buttons.forEach((b) => (b.disabled = false));
    }
  });
  return button;
}
