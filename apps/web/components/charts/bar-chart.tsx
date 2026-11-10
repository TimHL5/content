"use client";

import { useId, useState } from "react";

import type { Bin } from "@/lib/style-stats";

/**
 * Single-series column chart. One hue (the caption names the series, so no legend),
 * bars anchored to the baseline with rounded data-ends and a 2px gap, a direct label on
 * the tallest bar only, a hover/focus readout per column, and a table view.
 */
export function BarChart({
  bins,
  caption,
  unit,
  empty,
}: {
  bins: Bin[];
  caption: string;
  unit: string;
  /** Shown instead of the chart when every value is zero. */
  empty: string;
}) {
  const [active, setActive] = useState<number | null>(null);
  const captionId = useId();
  const max = Math.max(1, ...bins.map((b) => b.value));
  const peak = bins.findIndex((b) => b.value === max);
  const labelEvery = Math.ceil(bins.length / 7);
  const shown = active !== null ? bins[active] : undefined;

  if (bins.every((b) => b.value === 0)) {
    return (
      <figure>
        <figcaption className="mb-2 text-sm text-muted-foreground">{caption}</figcaption>
        <p className="flex h-32 items-center justify-center rounded-lg bg-muted px-4 text-center text-sm text-muted-foreground">
          {empty}
        </p>
      </figure>
    );
  }

  return (
    <figure>
      <figcaption id={captionId} className="mb-2 text-sm text-muted-foreground">
        {caption}
      </figcaption>
      <div
        role="group"
        aria-labelledby={captionId}
        className="flex h-32 items-stretch gap-[2px] border-b border-chart-grid pt-5"
        onMouseLeave={() => setActive(null)}
      >
        {bins.map((bin, i) => (
          // The whole column is the hit target, not just the bar.
          <div
            key={bin.label}
            tabIndex={0}
            role="img"
            aria-label={`${bin.label}: ${bin.value} ${unit}`}
            className="relative flex min-w-0 flex-1 flex-col justify-end outline-none"
            onMouseEnter={() => setActive(i)}
            onFocus={() => setActive(i)}
            onBlur={() => setActive(null)}
          >
            {(i === peak || i === active) && bin.value > 0 && (
              <span className="mb-0.5 text-center text-[11px] font-medium tabular-nums">{bin.value}</span>
            )}
            <div
              className="rounded-t-[4px] bg-chart transition-opacity"
              style={{
                height: `${(bin.value / max) * 100}%`,
                opacity: active === null || active === i ? 1 : 0.45,
                minHeight: bin.value > 0 ? 2 : 0,
              }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-[2px]" aria-hidden>
        {bins.map((bin, i) => (
          <span key={bin.label} className="min-w-0 flex-1 text-center text-[11px] text-muted-foreground">
            {i % labelEvery === 0 ? <span className="whitespace-nowrap">{bin.label}</span> : null}
          </span>
        ))}
      </div>
      <p className="mt-1 h-4 text-xs text-muted-foreground" aria-live="polite">
        {shown ? `${shown.label}: ${shown.value} ${unit}` : ""}
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">View as table</summary>
        <table className="mt-2 w-full max-w-xs text-left tabular-nums">
          <tbody>
            {bins.map((bin) => (
              <tr key={bin.label} className="border-t border-border">
                <th scope="row" className="py-1 font-normal">
                  {bin.label}
                </th>
                <td className="py-1 text-right">
                  {bin.value} {unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
