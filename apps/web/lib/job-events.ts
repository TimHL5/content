import type { JobEvent } from "@stylecut/schemas";

export type JobStatus = JobEvent["status"];

const STATUSES: readonly string[] = ["queued", "running", "succeeded", "failed"];

export function isTerminal(status: JobStatus): boolean {
  return status === "succeeded" || status === "failed";
}

/** Parses the `data` of an SSE message. Returns null for anything that is not a JobEvent. */
export function parseJobEvent(data: unknown): JobEvent | null {
  if (typeof data !== "string") return null;
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.job_id !== "string") return null;
  if (typeof v.status !== "string" || !STATUSES.includes(v.status)) return null;
  if (typeof v.progress !== "number" || v.progress < 0 || v.progress > 1) return null;
  return value as JobEvent;
}

/**
 * Keeps the newest state. A stale `progress` event (reconnect snapshot racing a live
 * event) must never move a finished job back to running or the bar backwards.
 */
export function mergeJobEvent(previous: JobEvent | null, next: JobEvent): JobEvent {
  if (previous === null || previous.job_id !== next.job_id) return next;
  if (isTerminal(previous.status)) return previous;
  if (!isTerminal(next.status) && next.progress < previous.progress) return previous;
  return next;
}
