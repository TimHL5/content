"use client";

import type { ProjectCreateIn } from "@stylecut/schemas";
import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { ApiError, createProject, listStyleProfiles, startShootPlan } from "@/lib/api";

type Gear = NonNullable<NonNullable<ProjectCreateIn["brief"]["constraints"]>["gear"]>[number];

const GEAR: { id: Gear; label: string }[] = [
  { id: "phone", label: "Phone" },
  { id: "tripod", label: "Tripod" },
  { id: "gimbal", label: "Gimbal" },
  { id: "lav_mic", label: "Clip-on mic" },
  { id: "ring_light", label: "Ring light" },
  { id: "camera", label: "Camera" },
];

const inputClass =
  "min-h-11 w-full rounded-lg border border-border bg-background px-3 text-base outline-accent focus-visible:outline-2";

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium">{label}</span>
      {hint && <span className="text-muted-foreground">{hint}</span>}
      {children}
    </label>
  );
}

function lines(text: string): string[] {
  return text.split(/\n|,/).map((s) => s.trim()).filter(Boolean);
}

export function NewProject({ preselected }: { preselected: string | null }) {
  const router = useRouter();
  const styles = useQuery({ queryKey: ["style-profiles"], queryFn: listStyleProfiles });

  const [styleId, setStyleId] = useState(preselected ?? "");
  const [topic, setTopic] = useState("");
  const [points, setPoints] = useState("");
  const [script, setScript] = useState("");
  const [length, setLength] = useState("");
  const [locations, setLocations] = useState("");
  const [gear, setGear] = useState<Gear[]>(["phone"]);
  const [face, setFace] = useState(true);
  const [screen, setScreen] = useState(false);
  const [twoPeople, setTwoPeople] = useState(false);

  const chosen = styleId || styles.data?.[0]?.id || "";
  const style = styles.data?.find((s) => s.id === chosen);

  const create = useMutation({
    mutationFn: async () => {
      const seconds = Number(length);
      const project = await createProject({
        style_profile_id: chosen,
        title: topic.trim().slice(0, 80),
        brief: {
          topic: topic.trim(),
          key_points: lines(points),
          script: script.trim() || null,
          target_duration_s: length !== "" && Number.isFinite(seconds) ? seconds : null,
          constraints: {
            crew: twoPeople ? "two_person" : "solo",
            gear,
            locations: lines(locations),
            can_show_face: face,
            has_screen_content: screen,
          },
        },
      });
      // The plan is the point of the project: start it right away.
      await startShootPlan(project.id).catch(() => undefined);
      return project;
    },
    onSuccess: (project) => router.push(`/projects/${project.id}`),
  });

  if (styles.isPending) return <p className="text-sm text-muted-foreground">Loading your styles…</p>;
  if (styles.isError || styles.data.length === 0) {
    return (
      <Card>
        <CardTitle>{styles.isError ? "Couldn't load your styles" : "You need a style first"}</CardTitle>
        <CardDescription>
          {styles.isError ? "Check that the API is running, then reload." : "A project is filmed and edited in a style learned from a video you like."}
        </CardDescription>
        {!styles.isError && (
          <Link href="/styles/new" className={`${buttonVariants()} mt-3`}>
            Create a style
          </Link>
        )}
      </Card>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (topic.trim() !== "" && chosen !== "" && !create.isPending) create.mutate();
  };
  const error = create.error instanceof ApiError ? create.error.message : create.isError ? "Couldn't create the project. Try again." : null;

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Card className="flex flex-col gap-4">
        <Field label="Style">
          <select value={chosen} onChange={(e) => setStyleId(e.target.value)} className={inputClass}>
            {styles.data.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="What's the video about?" hint="One line is enough.">
          <textarea required value={topic} onChange={(e) => setTopic(e.target.value)} rows={2} maxLength={500} placeholder="3 mistakes first-time renters make" className={`${inputClass} py-2`} />
        </Field>
        <Field label="Points to cover (optional)" hint="One per line.">
          <textarea value={points} onChange={(e) => setPoints(e.target.value)} rows={3} className={`${inputClass} py-2`} />
        </Field>
        <Field label="Length in seconds (optional)" hint={style ? `Leave empty to match the style: ${Math.round(style.duration_s)}s.` : undefined}>
          <input type="number" inputMode="numeric" min={5} max={180} value={length} onChange={(e) => setLength(e.target.value)} className={inputClass} />
        </Field>
      </Card>

      <Card className="flex flex-col gap-4">
        <CardTitle>What you have to work with</CardTitle>
        <Field label="Where can you film? (optional)" hint="Separate with commas: home office, kitchen, street.">
          <input value={locations} onChange={(e) => setLocations(e.target.value)} className={inputClass} />
        </Field>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Gear</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {GEAR.map(({ id, label }) => (
              <label key={id} className="flex min-h-11 items-center gap-2 rounded-lg border border-border px-3 text-sm">
                <input
                  type="checkbox"
                  checked={gear.includes(id)}
                  onChange={(e) => setGear((g) => (e.target.checked ? [...g, id] : g.filter((x) => x !== id)))}
                  className="size-4 accent-[var(--accent)]"
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex flex-col gap-2">
          {[
            { label: "I'm comfortable showing my face", value: face, set: setFace },
            { label: "I have screen recordings or an app to show", value: screen, set: setScreen },
            { label: "Someone can help me film", value: twoPeople, set: setTwoPeople },
          ].map(({ label, value, set }) => (
            <label key={label} className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" checked={value} onChange={(e) => set(e.target.checked)} className="size-4 accent-[var(--accent)]" />
              {label}
            </label>
          ))}
        </div>
      </Card>

      <details className="rounded-xl border border-border bg-card p-4">
        <summary className="cursor-pointer text-sm font-medium">I already have a script</summary>
        <p className="mt-2 text-sm text-muted-foreground">We keep your wording and fit it to the style&apos;s structure and pace.</p>
        <textarea value={script} onChange={(e) => setScript(e.target.value)} rows={6} aria-label="Your script" className={`${inputClass} mt-2 py-2`} />
      </details>

      {error !== null && (
        <p role="alert" className="rounded-lg border border-bad px-3 py-2 text-sm text-bad">
          {error}
        </p>
      )}
      <Button type="submit" disabled={create.isPending || topic.trim() === ""} className="sm:self-start">
        {create.isPending ? "Creating…" : "Create plan"}
      </Button>
    </form>
  );
}
