/**
 * Exponential backoff for repeated background calls (polling, lazy loads).
 *
 * A page whose requests start failing - session expired, server restarting,
 * or its address blocked by the tunnel allowlist - must not keep firing the
 * same request every few seconds: that floods the server, the access log and
 * the "blocked requests" notification. After each failure the next attempt
 * waits twice as long (baseMs, 2x, 4x ... up to maxMs); one success resets it.
 *
 * @param {{ baseMs?: number, maxMs?: number }} [options]
 */
export function createBackoff({ baseMs = 5000, maxMs = 5 * 60 * 1000 } = {}) {
  let failures = 0;
  let nextAt = 0;
  return {
    /** True when a call may be attempted now. */
    ready(now = Date.now()) {
      return now >= nextAt;
    },
    fail(now = Date.now()) {
      failures += 1;
      nextAt = now + Math.min(maxMs, baseMs * 2 ** (failures - 1));
    },
    succeed() {
      failures = 0;
      nextAt = 0;
    },
    get failures() {
      return failures;
    },
  };
}
