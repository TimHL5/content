"use client";

import { useQuery } from "@tanstack/react-query";
import { Clapperboard } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { listProjects } from "@/lib/api";

export function ProjectsList() {
  const { data, isPending, isError } = useQuery({ queryKey: ["projects"], queryFn: listProjects });

  if (isPending) return <p className="text-sm text-muted-foreground">Loading projects…</p>;
  if (isError) {
    return (
      <Card role="alert">
        <CardTitle>Couldn&apos;t load your projects</CardTitle>
        <CardDescription>Check that the API is running, then reload.</CardDescription>
      </Card>
    );
  }
  if (data.length === 0) {
    return (
      <EmptyState
        icon={Clapperboard}
        title="No projects yet"
        body="A project pairs a style with your topic: a shoot plan first, then your footage, then the edit."
      />
    );
  }
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {data.map((project) => (
        <li key={project.id}>
          <Link href={`/projects/${project.id}`} className="block rounded-xl outline-accent focus-visible:outline-2">
            <Card className="h-full transition-colors hover:bg-muted">
              <div className="flex items-start justify-between gap-3">
                <CardTitle className="text-base">{project.title}</CardTitle>
                <Badge tone={project.has_plan ? "ok" : "neutral"}>{project.has_plan ? "Plan ready" : "No plan yet"}</Badge>
              </div>
              <CardDescription className="mt-1 line-clamp-2">{project.brief.topic}</CardDescription>
              <p className="mt-3 text-xs text-muted-foreground">{project.style_name ? `Style: ${project.style_name}` : "Style deleted"}</p>
            </Card>
          </Link>
        </li>
      ))}
    </ul>
  );
}
