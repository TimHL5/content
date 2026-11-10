import type { Metadata } from "next";

import { NewStyle } from "./new-style";

export const metadata: Metadata = { title: "New style" };

export default function NewStylePage() {
  return (
    <>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">New style</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Start from a short video whose look you want. We study how it&apos;s made and never reuse its footage or audio.
      </p>
      <NewStyle />
    </>
  );
}
