"use client";

import type { CheckResult } from "@stylecut/schemas";
import { useQuery } from "@tanstack/react-query";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { fetchHealth } from "@/lib/api";

interface Tile {
  name: string;
  detail: string;
  tone: BadgeTone;
  label: string;
}

function dependencyTile(name: string, check: CheckResult | undefined, apiUp: boolean, loading: boolean): Tile {
  if (loading) return { name, detail: "Checking…", tone: "pending", label: "Checking" };
  if (!apiUp || check === undefined) {
    return { name, detail: "Unknown while the API is unreachable", tone: "neutral", label: "Unknown" };
  }
  if (check.ok) {
    return { name, detail: `Responded in ${check.latency_ms ?? "?"} ms`, tone: "ok", label: "Healthy" };
  }
  return { name, detail: check.error ?? "Check failed", tone: "bad", label: "Down" };
}

export function HealthTiles() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 5_000,
    retry: false,
  });

  const apiUp = data !== undefined && !isError;
  const apiTile: Tile = isPending
    ? { name: "API", detail: "Checking…", tone: "pending", label: "Checking" }
    : apiUp
      ? { name: "API", detail: "Reachable", tone: "ok", label: "Healthy" }
      : { name: "API", detail: "No response. Is `make dev` running?", tone: "bad", label: "Down" };

  const tiles: Tile[] = [
    apiTile,
    dependencyTile("Database", data?.checks.db, apiUp, isPending),
    dependencyTile("Redis", data?.checks.redis, apiUp, isPending),
    dependencyTile("Storage", data?.checks.s3, apiUp, isPending),
  ];

  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {tiles.map((tile) => (
        <li key={tile.name}>
          <Card className="flex items-center justify-between gap-4" data-testid={`health-${tile.name.toLowerCase()}`}>
            <div className="min-w-0">
              <CardTitle>{tile.name}</CardTitle>
              <CardDescription className="truncate">{tile.detail}</CardDescription>
            </div>
            <Badge tone={tile.tone}>
              <span className="size-1.5 rounded-full bg-current" aria-hidden />
              {tile.label}
            </Badge>
          </Card>
        </li>
      ))}
    </ul>
  );
}
