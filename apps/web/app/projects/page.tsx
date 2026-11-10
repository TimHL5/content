import { Clapperboard } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = { title: "Projects" };

export default function ProjectsPage() {
  return (
    <>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Projects</h1>
      <EmptyState
        icon={Clapperboard}
        title="No projects yet"
        body="A project pairs a style with your topic: a shoot plan first, then your footage, then the edit."
      />
    </>
  );
}
