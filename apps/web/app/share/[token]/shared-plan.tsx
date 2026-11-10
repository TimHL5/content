"use client";

import { useQuery } from "@tanstack/react-query";
import { FileDown } from "lucide-react";

import { PlanView } from "@/components/plan/plan-view";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { getSharedPlan, sharedPlanPdfUrl } from "@/lib/api";

/** The read-only view behind a share link: the plan, the checklist, the teleprompter. */
export function SharedPlan({ token }: { token: string }) {
  const plan = useQuery({ queryKey: ["shared-plan", token], queryFn: () => getSharedPlan(token), retry: false });

  if (plan.isPending) return <p className="text-sm text-muted-foreground">Loading plan…</p>;
  if (plan.isError) {
    return (
      <Card role="alert">
        <CardTitle>This link doesn&apos;t work</CardTitle>
        <CardDescription>The plan may have been unshared or deleted. Ask whoever sent it for a new link.</CardDescription>
      </Card>
    );
  }
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">{plan.data.title}</h1>
      <p className="mb-4 mt-1 text-sm text-muted-foreground">
        Shoot plan · {Math.round(plan.data.plan.target_duration_s)}s · view only
      </p>
      <PlanView
        data={plan.data}
        actions={null}
        footer={
          <a href={sharedPlanPdfUrl(token)} target="_blank" rel="noreferrer" className={`${buttonVariants({ variant: "outline" })} self-start`}>
            <FileDown className="size-4" aria-hidden />
            Open as PDF
          </a>
        }
      />
    </>
  );
}
