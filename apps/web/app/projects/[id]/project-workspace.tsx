"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDown, Share2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PlanView, type PlanActions } from "@/components/plan/plan-view";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { useJob } from "@/hooks/use-job";
import {
  ApiError,
  deleteProject,
  getProject,
  getShootPlan,
  patchShootPlan,
  planPdfUrl,
  regenerateShootPlan,
  sharePlan,
  startShootPlan,
} from "@/lib/api";

function Progress({ label, fraction }: { label: string; fraction: number }) {
  const percent = Math.round(fraction * 100);
  return (
    <Card>
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className="truncate text-muted-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">{percent}%</span>
      </div>
      <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${percent}%` }} />
      </div>
    </Card>
  );
}

export function ProjectWorkspace({ id }: { id: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const project = useQuery({ queryKey: ["project", id], queryFn: () => getProject(id), retry: false });
  const hasPlan = project.data?.has_plan ?? false;
  const plan = useQuery({ queryKey: ["shoot-plan", id], queryFn: () => getShootPlan(id), enabled: hasPlan, retry: false });

  // Follow whichever plan job is newest: one we just started, or one already running.
  const [startedJob, setStartedJob] = useState<string | null>(null);
  const jobId = startedJob ?? project.data?.plan_job_id ?? null;
  const { event } = useJob(jobId);
  const status = event?.status ?? null;
  const working = jobId !== null && (status === null || status === "queued" || status === "running") && (startedJob !== null || !hasPlan);

  useEffect(() => {
    if (status === "succeeded") {
      void queryClient.invalidateQueries({ queryKey: ["project", id] });
      void queryClient.invalidateQueries({ queryKey: ["shoot-plan", id] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [status, id, queryClient]);

  const start = useMutation({ mutationFn: () => startShootPlan(id), onSuccess: (job) => setStartedJob(job.job_id) });
  const regenerate = useMutation({
    mutationFn: (body: Parameters<typeof regenerateShootPlan>[1]) => regenerateShootPlan(id, body),
    onSuccess: (job) => setStartedJob(job.job_id),
  });
  const patch = useMutation({
    mutationFn: (body: Parameters<typeof patchShootPlan>[1]) => patchShootPlan(id, body),
    onSuccess: (data) => queryClient.setQueryData(["shoot-plan", id], data),
  });
  const share = useMutation({ mutationFn: () => sharePlan(id) });
  const remove = useMutation({
    mutationFn: () => deleteProject(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push("/projects");
    },
  });
  const [copied, setCopied] = useState(false);

  if (project.isPending) return <p className="text-sm text-muted-foreground">Loading project…</p>;
  if (project.isError) {
    const missing = project.error instanceof ApiError && project.error.status === 404;
    return (
      <Card role="alert">
        <CardTitle>{missing ? "This project doesn't exist" : "Couldn't load this project"}</CardTitle>
        <CardDescription>{missing ? "It may have been deleted." : "Check that the API is running and try again."}</CardDescription>
      </Card>
    );
  }

  const failed = status === "failed" && (startedJob !== null || !hasPlan);
  const mutationError = [start.error, regenerate.error, patch.error, share.error].find((e) => e != null);
  const errorText = mutationError instanceof ApiError ? mutationError.message : mutationError ? "That didn't go through. Try again." : null;
  const shareUrl = share.data ? `${window.location.origin}${share.data.path}` : null;

  const actions: PlanActions = {
    patch: (body) => patch.mutate(body),
    regenerate: (scope, targetId, instruction) => regenerate.mutate({ scope, target_id: targetId, instruction }),
    busy: working || patch.isPending || regenerate.isPending,
  };

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{project.data.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {project.data.style_name ? (
            <>
              In the style of{" "}
              <Link href={`/styles/${project.data.style_profile_id}`} className="underline underline-offset-2">
                {project.data.style_name}
              </Link>
            </>
          ) : (
            "The style this project used was deleted."
          )}
          {plan.data ? ` · ${Math.round(plan.data.plan.target_duration_s)}s · version ${plan.data.version}` : ""}
        </p>
      </header>

      {working && <Progress label={event?.step ?? "Starting…"} fraction={event?.progress ?? 0} />}

      {failed && (
        <Card role="alert" className="border-bad">
          <CardTitle>{event?.error ?? "The plan couldn't be written."}</CardTitle>
          <CardDescription>{hasPlan ? "Your current plan is unchanged." : "Nothing was saved."}</CardDescription>
          <Button className="mt-3" onClick={() => start.mutate()} disabled={start.isPending}>
            Try again
          </Button>
        </Card>
      )}
      {errorText !== null && (
        <p role="alert" className="rounded-lg border border-bad px-3 py-2 text-sm text-bad">
          {errorText}
        </p>
      )}

      {!hasPlan && !working && !failed && (
        <Card>
          <CardTitle>No shoot plan yet</CardTitle>
          <CardDescription>Get a script and a shot list that fit this style, in the order to film them.</CardDescription>
          <Button className="mt-3" onClick={() => start.mutate()} disabled={start.isPending || project.data.style_name === null}>
            Write my plan
          </Button>
        </Card>
      )}

      {plan.data && (
        <PlanView
          data={plan.data}
          actions={actions}
          footer={
            <Card>
              <CardTitle>Take it with you</CardTitle>
              <div className="mt-3 flex flex-wrap gap-2">
                <a href={planPdfUrl(id)} target="_blank" rel="noreferrer" className={buttonVariants({ variant: "outline" })}>
                  <FileDown className="size-4" aria-hidden />
                  Open as PDF
                </a>
                <Button variant="outline" onClick={() => share.mutate()} disabled={share.isPending}>
                  <Share2 className="size-4" aria-hidden />
                  {share.data ? "Link created" : "Create a share link"}
                </Button>
              </div>
              {shareUrl !== null && (
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input readOnly value={shareUrl} aria-label="Share link" onFocus={(e) => e.target.select()} className="min-h-11 w-full min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-sm" />
                  <Button
                    variant="outline"
                    onClick={() => {
                      void navigator.clipboard.writeText(shareUrl).then(() => setCopied(true));
                    }}
                  >
                    {copied ? "Copied" : "Copy"}
                  </Button>
                </div>
              )}
              {shareUrl !== null && <p className="mt-2 text-xs text-muted-foreground">Anyone with this link can view the plan. They can&apos;t change it.</p>}
            </Card>
          }
        />
      )}

      <div className="flex flex-wrap justify-end gap-2">
        {hasPlan && (
          <Button
            variant="outline"
            disabled={actions.busy}
            onClick={() => {
              if (window.confirm("Write a completely new plan? Your current one is kept as an earlier version.")) regenerate.mutate({ scope: "all" });
            }}
          >
            Start the plan over
          </Button>
        )}
        <Button
          variant="outline"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(`Delete "${project.data.title}" and its plan? This can't be undone.`)) remove.mutate();
          }}
        >
          Delete project
        </Button>
      </div>
    </div>
  );
}
