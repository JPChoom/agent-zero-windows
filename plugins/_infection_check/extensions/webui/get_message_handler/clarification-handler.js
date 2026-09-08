import { drawProcessStep } from "/js/messages.js";
import { callJsonApi } from "/js/api.js";

/**
 * Renders an infection-check clarification as a decision for the person
 * reading the chat.
 *
 * These questions are written for a human - "Are you okay with...",
 * "should it add an exception first?" - and used to be answered by the
 * main model, which replied in the user's voice and cleared its own gate.
 * The buttons are what make the question actually reach someone.
 */
export default async function registerClarificationHandler(extData) {
  if (extData?.type === "infection_check_clarification_request") {
    extData.handler = drawClarificationRequest;
  }
}

function drawClarificationRequest({ id, content, kvps, ...additional }) {
  const approvalId = kvps?.approval_id || "";
  const resolved = Boolean(kvps?.resolved);
  const outcome = kvps?.outcome || "";
  const toolName = kvps?.tool_name || "";
  const toolArgs = String(kvps?.tool_args || "");

  const title = resolved
    ? `Safety check: ${outcomeLabel(outcome)}`
    : "Safety check: your decision needed";

  const actionButtons = [];
  if (!resolved && approvalId) {
    actionButtons.push(
      createDecisionButton("Allow", "approve-btn", () =>
        respond(approvalId, true)
      )
    );
    actionButtons.push(
      createDecisionButton("Block", "deny-btn", () =>
        respond(approvalId, false)
      )
    );
  }

  // Show what is actually being gated. A question without the call it is
  // about is not enough to decide on.
  const detail = [content || ""];
  if (toolName) detail.push(`\nTool: ${toolName}`);
  if (toolArgs && toolArgs !== "{}") detail.push(`\n${toolArgs}`);

  return drawProcessStep({
    id,
    title,
    code: "SEC",
    classes: ["infection-check-clarification-step"],
    kvps: null,
    content: detail.join("").trim(),
    contentClasses: ["terminal-output"],
    actionButtons,
    log: {
      type: "infection_check_clarification_request",
      timestamp: additional?.timestamp,
      agentno: additional?.agentno || 0,
    },
  });
}

async function respond(approvalId, approved) {
  await callJsonApi("infection_clarify_respond", {
    approval_id: approvalId,
    approved,
  });
}

function outcomeLabel(outcome) {
  switch (outcome) {
    case "allowed":
      return "allowed";
    case "blocked":
      return "blocked";
    case "timeout":
      return "no answer - blocked";
    case "superseded":
      return "superseded by a newer prompt";
    case "error":
      return "could not be answered - blocked";
    default:
      return "resolved";
  }
}

function createDecisionButton(label, className, onClick) {
  const button = document.createElement("button");
  // type="button" so it never submits, and stopPropagation so clicking a
  // decision does not also toggle the process step it sits inside - both
  // learned from safety_policy's approval buttons.
  button.type = "button";
  button.className = `action-button infection-check-decision-btn ${className}`;
  button.textContent = label;
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    // Disable both: the future resolves once, so a second click is a no-op
    // that would still look to the user like it did something.
    const row = button.parentElement;
    const buttons = row ? [...row.querySelectorAll("button")] : [button];
    buttons.forEach((b) => (b.disabled = true));
    try {
      await onClick();
    } catch (error) {
      buttons.forEach((b) => (b.disabled = false));
      window.toastFrontendError?.(
        error?.message || "Failed to submit decision",
        "Safety check"
      );
    }
  });
  return button;
}
