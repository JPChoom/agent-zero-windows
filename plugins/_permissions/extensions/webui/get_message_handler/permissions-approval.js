import { drawProcessStep } from "/js/messages.js";
import { callJsonApi } from "/js/api.js";

export default async function registerPermissionsApproval(extData) {
  if (extData?.type === "permissions_approval_request") {
    extData.handler = drawPermissionRequest;
  }
}

function drawPermissionRequest({ id, content, kvps, ...additional }) {
  const approvalId = kvps?.approval_id || "";
  const resolved = Boolean(kvps?.resolved);
  const outcome = kvps?.outcome || "";
  const toolName = String(kvps?.tool_name || "tool");
  const target = String(kvps?.target || "");
  const suggested = String(kvps?.suggested_rule || "");
  const suggestedTool = String(kvps?.suggested_tool_rule || "");

  const title = resolved
    ? `Permission ${outcomeLabel(outcome)}: ${toolName}`
    : `Permission required: ${toolName}`;

  const actionButtons = [];
  if (!resolved && approvalId) {
    const respond = async (approved, remember) => {
      const result = await callJsonApi("permissions_respond", {
        approval_id: approvalId,
        approved,
        remember: remember || "",
      });
      // A rule that failed to save must be surfaced: the user would
      // otherwise believe they had stopped being asked when they had not.
      if (result?.error) {
        window.toastFrontendError?.(result.error, "Permissions");
      }
    };

    actionButtons.push(decisionButton("Allow once", "approve-btn", () => respond(true)));

    // "Always allow" writes a rule matching this exact call; the broader
    // whole-tool option is offered separately so widening the permission is
    // a deliberate second choice rather than the default.
    if (suggested) {
      actionButtons.push(
        decisionButton("Always allow this", "approve-btn", () => respond(true, suggested))
      );
    }
    if (suggestedTool && suggestedTool !== suggested) {
      actionButtons.push(
        decisionButton(`Always allow ${toolName}`, "approve-btn", () =>
          respond(true, suggestedTool)
        )
      );
    }
    actionButtons.push(decisionButton("Deny", "deny-btn", () => respond(false)));
  }

  return drawProcessStep({
    id,
    title,
    code: "PRM",
    classes: ["permissions-approval-step"],
    kvps: null,
    content: target ? `${content || ""}\n\n${target}`.trim() : content,
    contentClasses: ["terminal-output"],
    actionButtons,
    log: {
      type: "permissions_approval_request",
      timestamp: additional?.timestamp,
      agentno: additional?.agentno || 0,
    },
  });
}

function outcomeLabel(outcome) {
  switch (outcome) {
    case "approved": return "granted";
    case "denied": return "denied";
    case "timeout": return "timed out (denied)";
    default: return outcome || "resolved";
  }
}

function decisionButton(label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `action-button permissions-decision-btn ${className}`;
  button.textContent = label;
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    // Disable the whole row: a second click would resolve an already
    // settled future and read as a no-op the user cannot explain.
    const row = button.parentElement;
    [...(row ? row.querySelectorAll("button") : [button])].forEach((b) => (b.disabled = true));
    try {
      await handler();
    } catch (error) {
      window.toastFrontendError?.(error?.message || "Failed to submit decision", "Permissions");
      [...(row ? row.querySelectorAll("button") : [button])].forEach((b) => (b.disabled = false));
    }
  });
  return button;
}
