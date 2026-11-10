import type { Metadata } from "next";
import Link from "next/link";

import { StyleCard } from "./style-card";

export const metadata: Metadata = { title: "Style" };

export default async function StylePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <Link href="/styles" className="mb-4 inline-block text-sm text-muted-foreground underline-offset-2 hover:underline">
        ← All styles
      </Link>
      <StyleCard id={id} />
    </>
  );
}
