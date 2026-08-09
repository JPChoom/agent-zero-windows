import { callJsonApi } from "/js/api.js";

export async function killSwitchStatus() {
  try {
    return await callJsonApi("kill_switch", { action: "status" });
  } catch (error) {
    console.error("Failed to fetch kill switch status", error);
    return { tripped: false, reason: "" };
  }
}

export async function toggleKillSwitch(currentlyTripped) {
  const action = currentlyTripped ? "reset" : "trip";
  if (!currentlyTripped) {
    const confirmed = window.confirm(
      "This halts ALL code execution across every chat until a human resets it here. Continue?"
    );
    if (!confirmed) {
      return { tripped: currentlyTripped };
    }
  }
  try {
    return await callJsonApi("kill_switch", { action });
  } catch (error) {
    window.toastFrontendError?.(error?.message || "Failed to update kill switch", "Kill Switch");
    return { tripped: currentlyTripped };
  }
}
