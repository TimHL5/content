import type { Metadata } from "next";

import { NewProject } from "./new-project";

export const metadata: Metadata = { title: "New project" };

export default async function NewProjectPage({ searchParams }: { searchParams: Promise<{ style?: string }> }) {
  const { style } = await searchParams;
  return (
    <>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">New project</h1>
      <p className="mb-6 text-sm text-muted-foreground">Pick a style and say what your video is about. You&apos;ll get a script and a shot list to film.</p>
      <NewProject preselected={style ?? null} />
    </>
  );
}
