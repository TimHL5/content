import type { Metadata } from "next";

import { SharedPlan } from "./shared-plan";

export const metadata: Metadata = { title: "Shoot plan", robots: { index: false, follow: false } };

export default async function SharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <SharedPlan token={token} />;
}
