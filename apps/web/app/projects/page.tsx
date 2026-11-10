import { Plus } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

import { ProjectsList } from "./projects-list";

export const metadata: Metadata = { title: "Projects" };

export default function ProjectsPage() {
  return (
    <>
      <div className="mb-6 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <Link href="/projects/new" className={buttonVariants()}>
          <Plus className="size-4" aria-hidden />
          New project
        </Link>
      </div>
      <ProjectsList />
    </>
  );
}
