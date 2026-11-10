import type { Metadata } from "next";
import Link from "next/link";

import { ProjectWorkspace } from "./project-workspace";

export const metadata: Metadata = { title: "Project" };

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <Link href="/projects" className="mb-4 inline-block text-sm text-muted-foreground underline-offset-2 hover:underline">
        ← All projects
      </Link>
      <ProjectWorkspace id={id} />
    </>
  );
}
