import type { Metadata } from "next";

import { DemoJob } from "./demo-job";
import { HealthTiles } from "./health-tiles";

export const metadata: Metadata = { title: "System" };

export default function HealthPage() {
  return (
    <>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">System</h1>
      <p className="mb-6 text-sm text-muted-foreground">Checked every 5 seconds.</p>
      <HealthTiles />
      <DemoJob />
    </>
  );
}
