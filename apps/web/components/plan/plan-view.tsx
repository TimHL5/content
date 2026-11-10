"use client";

import type { ShootPlan, ShootPlanOut, ShootPlanPatch } from "@stylecut/schemas";
import { ArrowDown, ArrowUp, Check, MonitorPlay, RefreshCw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { budgetState, groupBySetup, moveItem, spokenText } from "@/lib/plan";
import { humanize, seconds } from "@/lib/style-stats";
import { cn } from "@/lib/utils";

import { Teleprompter } from "./teleprompter";

type Shot = ShootPlan["shots"][number];
type Tab = "script" | "shots" | "shoot";
type Scope = "hook" | "beat" | "shot";

export interface PlanActions {
  /** Save manual edits. Absent on the read-only shared page. */
  patch: (patch: ShootPlanPatch) => void;
  regenerate: (scope: Scope, targetId: string | null, instruction: string | null) => void;
  busy: boolean;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "script", label: "Script" },
  { id: "shots", label: "Shots" },
  { id: "shoot", label: "Shoot" },
];

function useChecked(storageKey: string): [Set<string>, (id: string) => void] {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  // Kept on this device so the checklist works on set without a connection.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      setChecked(new Set(raw ? (JSON.parse(raw) as string[]) : []));
    } catch {
      setChecked(new Set());
    }
  }, [storageKey]);
  const toggle = (id: string) =>
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        window.localStorage.setItem(storageKey, JSON.stringify([...next]));
      } catch {
        /* private mode: the checklist still works for this visit */
      }
      return next;
    });
  return [checked, toggle];
}

function AnotherOption({ label, onSubmit, disabled }: { label: string; onSubmit: (instruction: string | null) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm text-muted-foreground outline-accent hover:text-foreground focus-visible:outline-2 disabled:opacity-50"
      >
        <RefreshCw className="size-4" aria-hidden />
        {label}
      </button>
    );
  }
  return (
    <form
      className="mt-2 flex flex-col gap-2 sm:flex-row"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(instruction.trim() || null);
        setOpen(false);
        setInstruction("");
      }}
    >
      <input
        autoFocus
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        maxLength={500}
        placeholder="What should be different? (optional)"
        aria-label="What should be different? Optional."
        className="min-h-11 w-full min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-base outline-accent focus-visible:outline-2"
      />
      <Button type="submit" disabled={disabled}>
        Write another
      </Button>
      <Button type="button" variant="outline" onClick={() => setOpen(false)}>
        Cancel
      </Button>
    </form>
  );
}

function ScriptTab({ data, actions }: { data: ShootPlanOut; actions: PlanActions | null }) {
  const { plan, style, word_count: words } = data;
  const [editing, setEditing] = useState<string | null>(null);
  const state = budgetState(words, plan.word_budget);
  const fill = plan.word_budget > 0 ? Math.min(words / plan.word_budget, 1.25) / 1.25 : 0;

  if (plan.word_budget === 0 && plan.script.length === 0) {
    return (
      <Card>
        <CardTitle>No spoken script</CardTitle>
        <CardDescription>This style has no speech. The video is carried by the shots and on-screen text.</CardDescription>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <span className="font-medium">
            {words} of {plan.word_budget} words
          </span>
          <span className={cn("text-muted-foreground", state !== "ok" && "font-medium text-pending")}>
            {state === "ok" ? "Fits the style's pace" : state === "over" ? "Too long to say at this pace" : "Shorter than the style's pace"}
          </span>
        </div>
        <div className="relative mt-2 h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${words} of ${plan.word_budget} words`}>
          <div className={cn("h-full rounded-full", state === "ok" ? "bg-ok" : "bg-pending")} style={{ width: `${fill * 100}%` }} />
          {/* The budget sits at 80% of the bar, leaving room to show an overrun. */}
          <div className="absolute inset-y-0 left-[80%] w-px bg-foreground/40" aria-hidden />
        </div>
      </Card>

      {plan.title_options.length > 0 && (
        <Card>
          <CardTitle>On-screen title options</CardTitle>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {plan.title_options.map((option) => (
              <li key={option}>{option}</li>
            ))}
          </ul>
        </Card>
      )}

      {style.beats.map((beat) => {
        const lines = plan.script.filter((l) => l.beat_id === beat.id);
        if (lines.length === 0) return null;
        return (
          <Card key={beat.id} className={cn("border-l-4", beat.function === "hook" ? "border-l-chart" : "border-l-border")}>
            <div className="mb-2 flex items-center justify-between gap-3">
              <CardTitle>
                {humanize(beat.id)}
                {beat.must_have && <span className="ml-2 text-xs font-normal text-muted-foreground">must-have</span>}
              </CardTitle>
              <span className="text-xs text-muted-foreground tabular-nums">{seconds(lines.reduce((sum, l) => sum + l.est_duration_s, 0))}</span>
            </div>
            <ul className="flex flex-col gap-2">
              {lines.map((line) =>
                editing === line.id && actions !== null ? (
                  <li key={line.id}>
                    <textarea
                      autoFocus
                      defaultValue={line.text}
                      rows={3}
                      aria-label={`Edit line ${line.id}`}
                      className="w-full rounded-lg border border-border bg-background p-3 text-base outline-accent focus-visible:outline-2"
                      onBlur={(e) => {
                        const text = e.target.value.trim();
                        if (text !== "" && text !== line.text) actions.patch({ lines: [{ id: line.id, text }] });
                        setEditing(null);
                      }}
                    />
                  </li>
                ) : (
                  <li key={line.id}>
                    <button
                      type="button"
                      disabled={actions === null}
                      onClick={() => setEditing(line.id)}
                      className="w-full rounded-lg p-2 text-left text-base outline-accent enabled:hover:bg-muted focus-visible:outline-2"
                    >
                      {line.text}
                      {line.delivery_note && <span className="mt-1 block text-sm text-muted-foreground">({line.delivery_note})</span>}
                    </button>
                  </li>
                ),
              )}
            </ul>
            {actions !== null && (
              <AnotherOption
                label={beat.function === "hook" ? "Give me another hook" : "Another take on this part"}
                disabled={actions.busy}
                onSubmit={(instruction) => actions.regenerate(beat.function === "hook" ? "hook" : "beat", beat.id, instruction)}
              />
            )}
          </Card>
        );
      })}
    </div>
  );
}

function ShotMeta({ shot }: { shot: Shot }) {
  return (
    <p className="text-xs text-muted-foreground">
      {humanize(shot.kind)} · {shot.framing.toUpperCase()} · {humanize(shot.camera_motion).toLowerCase()} · {seconds(shot.duration_s)} on screen
    </p>
  );
}

function ShotsTab({ data, actions }: { data: ShootPlanOut; actions: PlanActions | null }) {
  const { plan } = data;
  const ids = plan.shots.map((s) => s.id);
  return (
    <ol className="flex flex-col gap-3">
      {plan.shots.map((shot, index) => {
        const spoken = spokenText(plan, shot);
        return (
          <li key={shot.id}>
            <Card>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold tabular-nums">{index + 1}</span>
                    <Badge tone={shot.priority === "must" ? "bad" : "neutral"}>{shot.priority === "must" ? "Must-have" : "Nice to have"}</Badge>
                    {shot.will_be_cut && <Badge tone="neutral">Will be cut up</Badge>}
                  </div>
                  <CardTitle className="text-base">{shot.description}</CardTitle>
                  <ShotMeta shot={shot} />
                </div>
                {actions !== null && (
                  <div className="flex shrink-0 flex-col gap-1">
                    <button
                      type="button"
                      aria-label={`Move shot ${index + 1} earlier`}
                      disabled={index === 0 || actions.busy}
                      onClick={() => actions.patch({ shot_order: moveItem(ids, shot.id, -1) })}
                      className="flex size-11 items-center justify-center rounded-lg border border-border outline-accent hover:bg-muted focus-visible:outline-2 disabled:opacity-30"
                    >
                      <ArrowUp className="size-4" aria-hidden />
                    </button>
                    <button
                      type="button"
                      aria-label={`Move shot ${index + 1} later`}
                      disabled={index === ids.length - 1 || actions.busy}
                      onClick={() => actions.patch({ shot_order: moveItem(ids, shot.id, 1) })}
                      className="flex size-11 items-center justify-center rounded-lg border border-border outline-accent hover:bg-muted focus-visible:outline-2 disabled:opacity-30"
                    >
                      <ArrowDown className="size-4" aria-hidden />
                    </button>
                  </div>
                )}
              </div>
              {spoken !== "" && <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-sm">“{spoken}”</p>}
              <p className="mt-3 text-sm">{shot.direction}</p>
              {(shot.alternatives ?? []).length > 0 && (
                <p className="mt-2 text-sm text-muted-foreground">If you can&apos;t get it: {(shot.alternatives ?? []).join("; ")}</p>
              )}
              {actions !== null && (
                <AnotherOption label="Another way to film this" disabled={actions.busy} onSubmit={(instruction) => actions.regenerate("shot", shot.id, instruction)} />
              )}
            </Card>
          </li>
        );
      })}
    </ol>
  );
}

function ShootTab({ data, storageKey }: { data: ShootPlanOut; storageKey: string }) {
  const { plan, style } = data;
  const [checked, toggle] = useChecked(storageKey);
  const [prompting, setPrompting] = useState<Shot | null>(null);
  const groups = groupBySetup(plan);
  const done = plan.shots.filter((s) => checked.has(s.id)).length;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium">
            {done} of {plan.shots.length} shots filmed
          </span>
          <span className="text-muted-foreground">
            {groups.length} setup{groups.length === 1 ? "" : "s"}
          </span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={plan.shots.length} aria-valuenow={done} aria-label="Shots filmed">
          <div className="h-full rounded-full bg-ok transition-[width]" style={{ width: `${plan.shots.length ? (done / plan.shots.length) * 100 : 0}%` }} />
        </div>
        {(plan.checklist_notes ?? []).length > 0 && (
          <ul className="mt-3 list-disc pl-5 text-sm text-muted-foreground">
            {(plan.checklist_notes ?? []).map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </Card>

      {groups.map((group, index) => (
        <section key={group.setupId} aria-label={`Setup ${index + 1}`}>
          <Card className="rounded-b-none border-b-0 bg-muted">
            <CardTitle>
              Setup {index + 1}: {group.setup?.location ?? group.setupId}
            </CardTitle>
            {group.setup !== null && (
              <dl className="mt-2 grid gap-1 text-sm">
                <div><dt className="inline font-medium">Framing: </dt><dd className="inline">{group.setup.framing_summary}</dd></div>
                <div><dt className="inline font-medium">Light: </dt><dd className="inline">{group.setup.lighting}</dd></div>
                <div><dt className="inline font-medium">Sound: </dt><dd className="inline">{group.setup.audio}</dd></div>
                {(group.setup.props?.length ?? 0) > 0 && (
                  <div><dt className="inline font-medium">Props: </dt><dd className="inline">{group.setup.props?.join(", ")}</dd></div>
                )}
              </dl>
            )}
          </Card>
          <ul className="overflow-hidden rounded-b-xl border border-border bg-card">
            {group.shots.map((shot) => {
              const isDone = checked.has(shot.id);
              const spoken = spokenText(plan, shot);
              return (
                <li key={shot.id} className="flex items-stretch border-t border-border first:border-t-0">
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={isDone}
                    onClick={() => toggle(shot.id)}
                    className="flex min-h-16 min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left outline-accent hover:bg-muted focus-visible:outline-2 focus-visible:-outline-offset-2"
                  >
                    <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full border-2", isDone ? "border-ok bg-ok text-white" : "border-border")} aria-hidden>
                      {isDone && <Check className="size-4" />}
                    </span>
                    <span className="min-w-0">
                      <span className={cn("block font-medium", isDone && "text-muted-foreground line-through")}>{shot.description}</span>
                      <span className="block text-xs text-muted-foreground">
                        {shot.takes} take{shot.takes === 1 ? "" : "s"} · record {seconds(shot.record_s)}
                        {shot.priority === "must" ? " · must-have" : ""}
                      </span>
                      {spoken !== "" && <span className="mt-1 block truncate text-sm text-muted-foreground">“{spoken}”</span>}
                    </span>
                  </button>
                  {spoken !== "" && (
                    <button
                      type="button"
                      onClick={() => setPrompting(shot)}
                      aria-label={`Open teleprompter for: ${shot.description}`}
                      className="flex w-16 shrink-0 flex-col items-center justify-center gap-1 border-l border-border text-xs text-muted-foreground outline-accent hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2"
                    >
                      <MonitorPlay className="size-5" aria-hidden />
                      Prompt
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {prompting !== null && (
        <Teleprompter
          title={prompting.description}
          wpm={style.wpm}
          lines={plan.script
            .filter((l) => (prompting.line_ids ?? []).includes(l.id))
            .map((l) => ({ text: l.text, emphasis: l.emphasis_words ?? [], note: l.delivery_note ?? null }))}
          onClose={() => setPrompting(null)}
        />
      )}
    </div>
  );
}

/** The three plan screens. `actions` is null on the read-only shared page. */
export function PlanView({ data, actions, footer }: { data: ShootPlanOut; actions: PlanActions | null; footer?: ReactNode }) {
  const [tab, setTab] = useState<Tab>("script");
  const { plan } = data;
  const warnings = plan.warnings ?? [];

  return (
    <div className="flex flex-col gap-4">
      {warnings.length > 0 && (
        <details className="rounded-xl border border-pending bg-pending-bg px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium">
            {warnings.length} thing{warnings.length === 1 ? "" : "s"} worth a second look
          </summary>
          <ul className="mt-2 list-disc pl-5">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}

      <div role="tablist" aria-label="Plan views" className="sticky top-0 z-10 grid grid-cols-3 gap-1 rounded-xl border border-border bg-card p-1">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            onClick={() => setTab(id)}
            className={cn(
              "min-h-11 rounded-lg text-sm font-medium outline-accent focus-visible:outline-2",
              tab === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "script" && <ScriptTab data={data} actions={actions} />}
        {tab === "shots" && <ShotsTab data={data} actions={actions} />}
        {tab === "shoot" && <ShootTab data={data} storageKey={`stylecut:checked:${data.project_id}:v${data.version}`} />}
      </div>

      {plan.music_brief && tab !== "shoot" && (
        <Card>
          <CardTitle>Music</CardTitle>
          <CardDescription>{plan.music_brief}</CardDescription>
        </Card>
      )}
      {footer}
    </div>
  );
}
