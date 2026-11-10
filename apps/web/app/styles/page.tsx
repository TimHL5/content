import { Plus } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

import { StylesList } from "./styles-list";

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
      <StylesList />
    </>
  );
}
