"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { listStyleProfiles } from "@/lib/api";
import { humanize, seconds } from "@/lib/style-stats";

export function StylesList() {
  const { data, isPending, isError } = useQuery({ queryKey: ["style-profiles"], queryFn: listStyleProfiles });

  if (isPending) return <p className="text-sm text-muted-foreground">Loading styles…</p>;
  if (isError) {
    return (
      <Card role="alert">
        <CardTitle>Couldn&apos;t load your styles</CardTitle>
        <CardDescription>Check that the API is running, then reload.</CardDescription>
      </Card>
    );
  }
  if (data.length === 0) {
    return (
      <EmptyState
        icon={Sparkles}
        title="No styles yet"
        body="A style is the pacing, captions, zooms, and hook of a video you like, saved so you can reuse it."
      />
    );
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {data.map((style) => (
        <li key={style.id}>
          <Link href={`/styles/${style.id}`} className="block rounded-xl outline-accent focus-visible:outline-2">
            <Card className="h-full transition-colors hover:bg-muted">
              <CardTitle className="text-base">{style.name}</CardTitle>
              <CardDescription className="mt-1 line-clamp-2">{style.summary}</CardDescription>
              <p className="mt-3 text-xs text-muted-foreground">
                {humanize(style.hook_type)} hook · {style.shot_count} shots · {seconds(style.duration_s)}
              </p>
            </Card>
          </Link>
        </li>
      ))}
    </ul>
  );
}
