"use client";

import type { JobEvent } from "@stylecut/schemas";
import { useEffect, useState } from "react";

import { API_URL } from "@/lib/api";
import { isTerminal, mergeJobEvent, parseJobEvent } from "@/lib/job-events";

export interface JobState {
  /** Latest known state of the job; null until the first event arrives. */
  event: JobEvent | null;
  /** True while the stream is disconnected and the browser is retrying. */
  reconnecting: boolean;
}

const IDLE: JobState = { event: null, reconnecting: false };

/**
 * Live progress for one job over SSE (`GET /jobs/{id}/events`).
 * The one hook every screen uses to follow a long-running operation.
 */
export function useJob(jobId: string | null): JobState {
  const [state, setState] = useState<JobState>(IDLE);

  useEffect(() => {
    if (jobId === null) {
      setState(IDLE);
      return;
    }
    setState(IDLE);
    const source = new EventSource(`${API_URL}/jobs/${jobId}/events`);

    const onMessage = (raw: Event) => {
      // The server's `error` event shares its name with EventSource's own connection
      // error. Only the server's carries data.
      const event = parseJobEvent((raw as MessageEvent<unknown>).data);
      if (event === null) {
        if (raw.type === "error") setState((s) => ({ ...s, reconnecting: true }));
        return;
      }
      setState((s) => ({ event: mergeJobEvent(s.event, event), reconnecting: false }));
      if (isTerminal(event.status)) source.close();
    };

    source.addEventListener("progress", onMessage);
    source.addEventListener("done", onMessage);
    source.addEventListener("error", onMessage);
    return () => source.close();
  }, [jobId]);

  return state;
}
