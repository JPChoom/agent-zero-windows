import { drawProcessStep } from "/js/messages.js";
import { callJsonApi } from "/js/api.js";

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

  const title = resolved
    ? `Safety policy: ${outcomeLabel(outcome)} (${category})`
    : `Safety policy: approval required (${category})`;

  const actionButtons = [];
  if (!resolved && approvalId) {
    actionButtons.push(
      createDecisionButton("Approve", "approve-btn", async () => {
        await callJsonApi("safety_policy_approve", { approval_id: approvalId, approved: true });
      }),
    );
    actionButtons.push(
      createDecisionButton("Deny", "deny-btn", async () => {
        await callJsonApi("safety_policy_approve", { approval_id: approvalId, approved: false });
      }),
    );
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
    button.disabled = true;
    try {
      await handler();
    } catch (error) {
      window.toastFrontendError?.(error?.message || "Failed to submit decision", "Safety Policy");
      button.disabled = false;
    }
  });
  return button;
}
