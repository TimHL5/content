import { Plus, Sparkles } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { buttonVariants } from "@/components/ui/button";

export const metadata: Metadata = { title: "Styles" };

export default function StylesPage() {
  return (
    <>
      <div className="mb-6 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Styles</h1>
        <Link href="/styles/new" className={buttonVariants()}>
          <Plus className="size-4" aria-hidden />
          New style
        </Link>
      </div>
      <EmptyState
        icon={Sparkles}
        title="No styles yet"
        body="A style is the pacing, captions, zooms, and hook of a video you like, saved so you can reuse it."
      />
    </>
  );
}
