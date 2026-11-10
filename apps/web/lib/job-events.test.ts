import type { JobEvent } from "@stylecut/schemas";
import { describe, expect, it } from "vitest";

import { toApiError } from "./api";
import { isTerminal, mergeJobEvent, parseJobEvent } from "./job-events";

const event = (overrides: Partial<JobEvent> = {}): JobEvent => ({
  job_id: "j1",
  status: "running",
  progress: 0.4,
  step: "Detecting cuts",
  eta_s: null,
  error: null,
  ...overrides,
});

describe("parseJobEvent", () => {
  it("parses a valid event", () => {
    expect(parseJobEvent(JSON.stringify(event()))).toEqual(event());
  });

  it("rejects non-events", () => {
    expect(parseJobEvent(undefined)).toBeNull(); // EventSource connection error has no data
    expect(parseJobEvent("not json")).toBeNull();
    expect(parseJobEvent(JSON.stringify({ job_id: "j1", status: "exploded", progress: 0 }))).toBeNull();
    expect(parseJobEvent(JSON.stringify(event({ progress: 1.5 })))).toBeNull();
  });
});

describe("mergeJobEvent", () => {
  it("takes the first event and forward progress", () => {
    expect(mergeJobEvent(null, event())).toEqual(event());
    expect(mergeJobEvent(event(), event({ progress: 0.6 })).progress).toBe(0.6);
  });

  it("ignores stale progress", () => {
    expect(mergeJobEvent(event({ progress: 0.6 }), event({ progress: 0.2 })).progress).toBe(0.6);
  });

  it("never leaves a terminal state", () => {
    const done = event({ status: "succeeded", progress: 1 });
    expect(mergeJobEvent(done, event({ progress: 0.9 }))).toEqual(done);
    expect(mergeJobEvent(event({ progress: 0.9 }), event({ status: "failed", progress: 0.3 })).status).toBe(
      "failed",
    );
  });

  it("switches to a different job", () => {
    expect(mergeJobEvent(event({ status: "succeeded", progress: 1 }), event({ job_id: "j2" })).job_id).toBe("j2");
  });
});

describe("isTerminal", () => {
  it("is true only for succeeded and failed", () => {
    expect(["queued", "running", "succeeded", "failed"].map((s) => isTerminal(s as JobEvent["status"]))).toEqual([
      false,
      false,
      true,
      true,
    ]);
  });
});

describe("toApiError", () => {
  it("reads the error envelope", () => {
    const err = toApiError(404, { error: { code: "JOB_NOT_FOUND", message: "Job not found.", hint: null } });
    expect([err.status, err.code, err.message, err.hint]).toEqual([404, "JOB_NOT_FOUND", "Job not found.", null]);
  });

  it("falls back for unexpected bodies", () => {
    expect(toApiError(502, "<html>bad gateway</html>").code).toBe("HTTP_502");
    expect(toApiError(500, null).message).toBe("Request failed (500).");
  });
});
