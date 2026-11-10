import { Sparkles } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = { title: "Styles" };

export default function StylesPage() {
  return (
    <>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Styles</h1>
      <EmptyState
        icon={Sparkles}
        title="No styles yet"
        body="A style is the pacing, captions, zooms, and hook of a video you like, saved so you can reuse it."
      />
    </>
  );
}
