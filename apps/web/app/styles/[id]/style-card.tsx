"use client";

import type { StyleProfile, StyleProfileOut } from "@stylecut/schemas";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { BarChart } from "@/components/charts/bar-chart";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { ApiError, deleteStyleProfile, getStyleProfile, patchStyleProfile } from "@/lib/api";
import { humanize, pacingBins, pacingLabel, percent, seconds, shotLengthHistogram, trim } from "@/lib/style-stats";
import { cn } from "@/lib/utils";

import { CaptionPreview } from "./caption-preview";

const PRESETS = ["bold_pop", "clean_subtle", "boxed", "karaoke", "minimal_lower"];
const FONTS = ["Montserrat ExtraBold", "Inter Bold", "Anton", "Poppins SemiBold", "Bebas Neue"];
const CASES = ["upper", "lower", "sentence", "title"];
const HIGHLIGHTS = ["none", "color", "box", "scale"];
const LOW_CONFIDENCE = 0.6;

function Section({
  title,
  confidence,
  children,
  className,
}: {
  title: string;
  confidence?: number;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <CardTitle className="text-base">{title}</CardTitle>
        {confidence !== undefined && confidence < LOW_CONFIDENCE && (
          <Badge tone="pending" title={`Confidence ${percent(confidence)}`}>
            Double-check
          </Badge>
        )}
      </div>
      {children}
    </Card>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
      {note && <dd className="text-xs text-muted-foreground">{note}</dd>}
    </div>
  );
}

function BeatTimeline({ profile }: { profile: StyleProfile }) {
  const duration = profile.source.duration_s || 1;
  return (
    <>
      {/* Identity is carried by the labels; shade only separates neighbors. */}
      <div className="flex h-9 w-full gap-[2px] overflow-hidden rounded-md" role="img" aria-label="Beats on a timeline">
        {profile.beats.map((beat, i) => (
          <div
            key={beat.id}
            title={`${humanize(beat.id)}: ${seconds(beat.start_s)} to ${seconds(beat.end_s)}`}
            className={cn(
              "flex min-w-0 items-center justify-center px-1 text-[11px] font-medium",
              beat.function === "hook"
                ? "bg-chart text-white"
                : i % 2
                  ? "bg-muted text-foreground"
                  : "bg-border text-foreground",
            )}
            style={{ width: `${((beat.end_s - beat.start_s) / duration) * 100}%` }}
          >
            <span className="truncate">{humanize(beat.id)}</span>
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-muted-foreground tabular-nums">
        <span>0s</span>
        <span>{seconds(duration)}</span>
      </div>
      <ol className="mt-3 flex flex-col gap-2">
        {profile.beats.map((beat) => (
          <li key={beat.id} className="flex gap-3 text-sm">
            <span className="w-20 shrink-0 text-muted-foreground tabular-nums">
              {trim(Math.round(beat.start_s * 10) / 10)}–{seconds(beat.end_s)}
            </span>
            <span className="min-w-0">
              <span className="font-medium">{humanize(beat.id)}</span>
              {beat.must_have && <span className="ml-2 text-xs text-muted-foreground">must-have</span>}
              <span className="block text-muted-foreground">{beat.technique}</span>
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}

function Field({ label, edited, onReset, children }: { label: string; edited: boolean; onReset: () => void; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="flex items-center justify-between gap-2 text-muted-foreground">
        {label}
        {edited && (
          <button type="button" onClick={onReset} className="text-xs underline underline-offset-2 hover:text-foreground">
            Reset
          </button>
        )}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "min-h-11 w-full rounded-lg border border-border bg-background px-3 text-base outline-accent focus-visible:outline-2";

export function StyleCard({ id }: { id: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["style-profile", id], queryFn: () => getStyleProfile(id), retry: false });
  const [name, setName] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (patch: Parameters<typeof patchStyleProfile>[1]) => patchStyleProfile(id, patch),
    onSuccess: (data: StyleProfileOut) => {
      queryClient.setQueryData(["style-profile", id], data);
      void queryClient.invalidateQueries({ queryKey: ["style-profiles"] });
      setName(null);
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteStyleProfile(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["style-profiles"] });
      router.push("/styles");
    },
  });

  if (query.isPending) return <p className="text-sm text-muted-foreground">Loading style…</p>;
  if (query.isError) {
    const missing = query.error instanceof ApiError && query.error.status === 404;
    return (
      <Card role="alert">
        <CardTitle>{missing ? "This style doesn't exist" : "Couldn't load this style"}</CardTitle>
        <CardDescription>{missing ? "It may have been deleted." : "Check that the API is running and try again."}</CardDescription>
        <Link href="/styles" className="mt-3 inline-block text-sm underline underline-offset-2">
          Back to styles
        </Link>
      </Card>
    );
  }

  const { profile, overrides, sheet_urls: sheets } = query.data;
  const { pacing, captions, speech, audio, rules, hook, color, confidence } = profile;
  const set = (pointer: string, value: unknown) => save.mutate({ overrides: { [pointer]: value } });
  const edited = (pointer: string) => pointer in overrides;
  const reset = (pointer: string) => () => set(pointer, null);
  const shotLengths = profile.shots.map((s) => s.end_s - s.start_s);
  const saveError = save.error instanceof ApiError ? save.error.message : save.isError ? "Couldn't save that change." : null;

  return (
    <div className="flex flex-col gap-4">
      <header>
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (name !== null && name.trim() !== "" && name !== query.data.name) save.mutate({ name });
          }}
        >
          <input
            aria-label="Style name"
            value={name ?? query.data.name}
            onChange={(e) => setName(e.target.value)}
            className="min-h-11 w-full min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-2 text-2xl font-semibold tracking-tight outline-accent hover:border-border focus-visible:border-border focus-visible:outline-2"
          />
          {name !== null && name.trim() !== "" && name !== query.data.name && (
            <Button type="submit" disabled={save.isPending}>
              Save name
            </Button>
          )}
        </form>
        <p className="mt-2 px-2 text-sm text-muted-foreground">{profile.summary}</p>
        <p className="mt-2 px-2 text-xs text-muted-foreground">
          {humanize(profile.source.platform)} · {seconds(profile.source.duration_s)} · {profile.source.aspect}
        </p>
      </header>

      {saveError !== null && (
        <p role="alert" className="rounded-lg border border-bad px-3 py-2 text-sm text-bad">
          {saveError}
        </p>
      )}

      <Section title="Hook" confidence={confidence.hook}>
        <p className="text-sm">
          <span className="font-medium">{humanize(hook.type)}</span>
          <span className="text-muted-foreground"> · first {seconds(hook.duration_s)}</span>
        </p>
        <p className="mt-2 rounded-lg bg-muted px-3 py-2 text-sm">{hook.template}</p>
        <p className="mt-2 text-sm text-muted-foreground">{hook.visual}</p>
      </Section>

      <Section title="Pacing">
        <dl className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Pace" value={pacingLabel(pacing.shot_len_s.median)} note={humanize(pacing.acceleration)} />
          <Stat label="Shots" value={String(pacing.shot_count)} />
          <Stat label="Typical shot" value={seconds(pacing.shot_len_s.median)} note={`${seconds(pacing.shot_len_s.min)} to ${seconds(pacing.shot_len_s.max)}`} />
          <Stat
            label="Cuts on the beat"
            value={pacing.cut_on_beat_pct === null || pacing.cut_on_beat_pct === undefined ? "–" : percent(pacing.cut_on_beat_pct)}
            note={audio.music_present ? undefined : "No music detected"}
          />
        </dl>
        <div className="grid gap-6 sm:grid-cols-2">
          <BarChart bins={pacingBins(pacing.cuts_per_5s)} caption="Cuts in each 5 seconds" unit="cuts" empty="No cuts: this video is a single take." />
          <BarChart bins={shotLengthHistogram(shotLengths)} caption="How long shots last" unit="shots" empty="No shots were found." />
        </div>
        <div className="mt-4 max-w-xs">
          <Field label="Longest shot the editor allows (seconds)" edited={edited("/pacing/max_shot_s")} onReset={reset("/pacing/max_shot_s")}>
            <input
              key={pacing.max_shot_s}
              type="number"
              min={0.5}
              max={30}
              step={0.1}
              defaultValue={pacing.max_shot_s}
              className={inputClass}
              onBlur={(e) => {
                const value = Number(e.target.value);
                if (Number.isFinite(value) && value > 0 && value !== pacing.max_shot_s) set("/pacing/max_shot_s", value);
              }}
            />
          </Field>
        </div>
      </Section>

      <Section title="Captions" confidence={confidence.captions}>
        <div className="grid gap-6 sm:grid-cols-[200px_1fr]">
          <CaptionPreview captions={captions} />
          <div className="grid content-start gap-3 sm:grid-cols-2">
            <Field label="Preset" edited={edited("/captions/preset")} onReset={reset("/captions/preset")}>
              <select value={captions.preset} onChange={(e) => set("/captions/preset", e.target.value)} className={inputClass}>
                {PRESETS.map((p) => (
                  <option key={p} value={p}>
                    {humanize(p)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Font" edited={edited("/captions/font_family")} onReset={reset("/captions/font_family")}>
              <select value={captions.font_family} onChange={(e) => set("/captions/font_family", e.target.value)} className={inputClass}>
                {FONTS.map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </Field>
            <Field label="Letter case" edited={edited("/captions/case")} onReset={reset("/captions/case")}>
              <select value={captions.case} onChange={(e) => set("/captions/case", e.target.value)} className={inputClass}>
                {CASES.map((c) => (
                  <option key={c} value={c}>
                    {humanize(c)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Active word" edited={edited("/captions/highlight")} onReset={reset("/captions/highlight")}>
              <select value={captions.highlight} onChange={(e) => set("/captions/highlight", e.target.value)} className={inputClass}>
                {HIGHLIGHTS.map((h) => (
                  <option key={h} value={h}>
                    {humanize(h)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Text color" edited={edited("/captions/fill")} onReset={reset("/captions/fill")}>
              <input type="color" value={captions.fill} onChange={(e) => set("/captions/fill", e.target.value.toUpperCase())} className="h-11 w-full rounded-lg border border-border bg-background p-1" />
            </Field>
            <Field label="Highlight color" edited={edited("/captions/highlight_color")} onReset={reset("/captions/highlight_color")}>
              <input
                type="color"
                value={captions.highlight_color ?? "#FFE600"}
                onChange={(e) => set("/captions/highlight_color", e.target.value.toUpperCase())}
                className="h-11 w-full rounded-lg border border-border bg-background p-1"
              />
            </Field>
            <p className="text-xs text-muted-foreground sm:col-span-2">
              {captions.words_per_chunk[0]}–{captions.words_per_chunk[1]} words at a time, {captions.lines} line{captions.lines === 1 ? "" : "s"},{" "}
              {humanize(captions.animation).toLowerCase()} animation. Matched to the closest font we render with.
            </p>
          </div>
        </div>
      </Section>

      <Section title="Structure" confidence={confidence.beats}>
        {profile.beats.length > 0 ? <BeatTimeline profile={profile} /> : <p className="text-sm text-muted-foreground">No beats were identified.</p>}
      </Section>

      <Section title="Editing" confidence={confidence.rules}>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="B-roll" value={percent(rules.broll_ratio)} note="of runtime" />
          <Stat
            label="Punch-ins"
            value={rules.punch_in_every_s ? `every ${seconds(rules.punch_in_every_s)}` : "None"}
            note={rules.punch_in_every_s ? `${rules.punch_in_scale.toFixed(2)}× zoom` : undefined}
          />
          <Stat label="Silences" value={rules.jump_cut_silences ? "Cut out" : "Kept"} />
          <Stat label="Ending" value={rules.loop_ending ? "Loops" : "Plain"} />
        </dl>
        <p className="mt-4 text-sm text-muted-foreground">
          Transitions: {rules.transitions.map((t) => humanize(t).toLowerCase()).join(", ")}.
          {rules.zoom_on.length > 0 && ` Zooms on: ${rules.zoom_on.map((z) => humanize(z).toLowerCase()).join(", ")}.`}
          {` Text cards: ${humanize(rules.text_card_usage).toLowerCase()}.`}
        </p>
      </Section>

      <Section title="Sound and speech" confidence={Math.min(confidence.audio ?? 1, confidence.speech ?? 1)}>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Speaking pace" value={speech.present ? `${Math.round(speech.wpm)} wpm` : "No speech"} note={speech.delivery ? humanize(speech.delivery) : undefined} />
          <Stat label="Talking" value={percent(speech.coverage_pct)} note="of runtime" />
          <Stat label="Music" value={audio.music_present && audio.bpm ? `${Math.round(audio.bpm)} BPM` : "None"} note={audio.music_mood ?? undefined} />
          <Stat label="Loudness" value={`${audio.integrated_lufs.toFixed(1)} LUFS`} note={`Sound effects: ${audio.sfx_density}`} />
        </dl>
      </Section>

      <Section title="Color" confidence={confidence.color}>
        <p className="text-sm">{humanize(color.look)}</p>
        <dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Brightness" value={percent(color.luma_mean)} />
          <Stat label="Contrast" value={color.contrast.toFixed(2)} />
          <Stat label="Saturation" value={percent(color.saturation)} />
          <Stat label="Warmth" value={color.warmth > 0.03 ? "Warm" : color.warmth < -0.03 ? "Cool" : "Neutral"} />
        </dl>
      </Section>

      {sheets.length > 0 && (
        <Section title="Frames from the reference" confidence={confidence.shots}>
          <p className="mb-3 text-sm text-muted-foreground">
            Low-resolution stills kept for reference. The video itself has been deleted and is never used in your edits.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {sheets.map((url, i) => (
              // eslint-disable-next-line @next/next/no-img-element -- presigned, short-lived URLs
              <img key={i} src={url} alt={`Contact sheet ${i + 1} of ${sheets.length}`} loading="lazy" className="w-full rounded-lg border border-border" />
            ))}
          </div>
        </Section>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <Link href={`/projects/new?style=${id}`} className={buttonVariants()}>
          Plan a video in this style
        </Link>
        <Button
          variant="outline"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(`Delete "${query.data.name}"? This can't be undone.`)) remove.mutate();
          }}
        >
          Delete style
        </Button>
      </div>
    </div>
  );
}
