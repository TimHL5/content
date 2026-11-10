"use client";

import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { useJob } from "@/hooks/use-job";
import { ApiError, createReference, getReference } from "@/lib/api";
import { referenceFileProblem, uploadFile } from "@/lib/upload";
import { cn } from "@/lib/utils";

interface Problem {
  message: string;
  hint: string | null;
}

type Phase =
  | { kind: "idle" }
  | { kind: "uploading"; fraction: number; name: string }
  | { kind: "starting" }
  | { kind: "processing"; jobId: string; referenceId: string; source: "url" | "upload" };

function toProblem(error: unknown): Problem {
  if (error instanceof ApiError) return { message: error.message, hint: error.hint };
  return { message: "Something went wrong.", hint: "Check your connection and try again." };
}

function ProgressBar({ label, fraction }: { label: string; fraction: number }) {
  const percent = Math.round(fraction * 100);
  return (
    <div data-testid="progress">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className="truncate text-muted-foreground">{label}</span>
        <span className="tabular-nums text-muted-foreground">{percent}%</span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function NewStyle() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [problem, setProblem] = useState<Problem | null>(null);
  const [url, setUrl] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const processing = phase.kind === "processing" ? phase : null;
  const { event, reconnecting } = useJob(processing?.jobId ?? null);
  const jobStatus = event?.status ?? null;

  // Once the job ends, the reference says what happened (and why, if it failed).
  const reference = useQuery({
    queryKey: ["reference", processing?.referenceId, jobStatus],
    queryFn: () => getReference(processing?.referenceId ?? ""),
    enabled: processing !== null && (jobStatus === "succeeded" || jobStatus === "failed"),
  });
  const styleId = jobStatus === "succeeded" ? (reference.data?.style_profile_id ?? null) : null;
  const router = useRouter();
  useEffect(() => {
    if (styleId !== null) router.replace(`/styles/${styleId}`);
  }, [styleId, router]);

  const failure: Problem | null =
    problem ??
    (jobStatus === "failed"
      ? {
          message: reference.data?.error?.message ?? event?.error ?? "We couldn't process that video.",
          hint: reference.data?.error?.hint ?? null,
        }
      : null);
  // Only a download problem is fixed by uploading the file yourself.
  const failedUrl =
    failure !== null && processing?.source === "url" && (reference.data?.error?.code ?? "").startsWith("INGEST_");
  const busy = phase.kind === "uploading" || phase.kind === "starting" || (processing !== null && jobStatus !== "failed");

  async function begin(source: { url: string } | { asset_id: string }, kind: "url" | "upload") {
    setPhase({ kind: "starting" });
    try {
      const accepted = await createReference(source);
      setPhase({ kind: "processing", jobId: accepted.job_id, referenceId: accepted.resource_id ?? "", source: kind });
    } catch (error) {
      setPhase({ kind: "idle" });
      setProblem(toProblem(error));
    }
  }

  function submitUrl(e: FormEvent) {
    e.preventDefault();
    if (busy || url.trim() === "") return;
    setProblem(null);
    void begin({ url: url.trim() }, "url");
  }

  async function submitFile(file: File | undefined) {
    if (file === undefined || busy) return;
    const invalid = referenceFileProblem(file);
    if (invalid !== null) {
      setPhase({ kind: "idle" });
      setProblem(invalid);
      return;
    }
    setProblem(null);
    setPhase({ kind: "uploading", fraction: 0, name: file.name });
    try {
      const assetId = await uploadFile(file, "reference", (fraction) =>
        setPhase({ kind: "uploading", fraction, name: file.name }),
      );
      await begin({ asset_id: assetId }, "upload");
    } catch (error) {
      setPhase({ kind: "idle" });
      setProblem(toProblem(error));
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    void submitFile(e.dataTransfer.files[0]);
  }

  if (styleId !== null) {
    return <p className="text-sm text-muted-foreground">Opening your new style…</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <form onSubmit={submitUrl}>
          <label htmlFor="reference-url" className="text-sm font-medium">
            Paste a link
          </label>
          <p className="mb-3 text-sm text-muted-foreground">TikTok, Instagram Reels, or YouTube Shorts. Up to 3 minutes.</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="reference-url"
              type="url"
              inputMode="url"
              autoComplete="off"
              placeholder="https://www.tiktok.com/@creator/video/…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={busy}
              className="min-h-11 w-full min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-base outline-accent focus-visible:outline-2 disabled:opacity-50"
            />
            <Button type="submit" disabled={busy || url.trim() === ""}>
              Use this video
            </Button>
          </div>
        </form>
      </Card>

      <button
        type="button"
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        disabled={busy}
        className={cn(
          "flex min-h-36 flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-8 text-center transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-50",
          dragging && "border-accent bg-muted",
        )}
      >
        <Upload className="mb-3 size-6 text-muted-foreground" aria-hidden />
        <span className="font-medium">Or upload the video file</span>
        <span className="mt-1 text-sm text-muted-foreground">Drop it here or tap to choose. MP4, MOV, or WebM, up to 200 MB.</span>
      </button>
      <input
        ref={fileInput}
        type="file"
        accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm"
        className="hidden"
        data-testid="reference-file"
        onChange={(e) => {
          void submitFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      {phase.kind === "uploading" && (
        <Card>
          <ProgressBar label={`Uploading ${phase.name}`} fraction={phase.fraction} />
        </Card>
      )}
      {(phase.kind === "starting" || (processing !== null && failure === null)) && (
        <Card>
          <ProgressBar
            label={reconnecting ? "Reconnecting…" : (event?.step ?? "Starting…")}
            fraction={event?.progress ?? 0}
          />
        </Card>
      )}

      {failure !== null && (
        <Card role="alert" className="border-bad" data-testid="problem">
          <CardTitle>{failure.message}</CardTitle>
          {failure.hint !== null && <CardDescription>{failure.hint}</CardDescription>}
          {failedUrl && (
            <Button className="mt-3" onClick={() => fileInput.current?.click()}>
              Upload the file instead
            </Button>
          )}
        </Card>
      )}
    </div>
  );
}
