"use client";

import { useMutation } from "@tanstack/react-query";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { useJob } from "@/hooks/use-job";
import { ApiError, startDemoJob } from "@/lib/api";
import type { JobStatus } from "@/lib/job-events";

const STATUS: Record<JobStatus, { tone: BadgeTone; label: string }> = {
  queued: { tone: "pending", label: "Queued" },
  running: { tone: "pending", label: "Running" },
  succeeded: { tone: "ok", label: "Succeeded" },
  failed: { tone: "bad", label: "Failed" },
};

function startErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "Test jobs are turned off. Set ENABLE_DEV_ROUTES=true in .env and restart the API.";
  }
  if (error instanceof ApiError) return error.message;
  return "Could not reach the API.";
}

/** Runs a 5-second no-op job to prove queue → worker → progress → SSE works end to end. */
export function DemoJob() {
  const start = useMutation({ mutationFn: startDemoJob });
  const jobId = start.data?.job_id ?? null;
  const { event, reconnecting } = useJob(jobId);

  const active = start.isPending || (jobId !== null && (event === null || event.status === "queued" || event.status === "running"));
  const percent = Math.round((event?.progress ?? 0) * 100);

  return (
    <Card className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle>Job pipeline</CardTitle>
          <CardDescription>Runs a 5-second test job through the worker and streams its progress.</CardDescription>
        </div>
        <Button onClick={() => start.mutate()} disabled={active}>
          {active ? "Running…" : "Run test job"}
        </Button>
      </div>

      {start.isError && (
        <p role="alert" className="mt-4 text-sm text-bad">
          {startErrorMessage(start.error)}
        </p>
      )}

      {jobId !== null && !start.isError && (
        <div className="mt-4" data-testid="demo-job">
          <div className="mb-2 flex items-center justify-between gap-3 text-sm">
            <span className="truncate text-muted-foreground">
              {reconnecting ? "Reconnecting…" : (event?.error ?? event?.step ?? "Waiting for a worker…")}
            </span>
            {event !== null && <Badge tone={STATUS[event.status].tone}>{STATUS[event.status].label}</Badge>}
          </div>
          <div
            role="progressbar"
            aria-label="Test job progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="h-2 overflow-hidden rounded-full bg-muted"
          >
            <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${percent}%` }} />
          </div>
        </div>
      )}
    </Card>
  );
}
