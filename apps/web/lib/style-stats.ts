/** Pure helpers behind the Style Card charts. */

export interface Bin {
  label: string;
  value: number;
}

/** Shot lengths bucketed into 0.5s bins; everything from `capS` up shares the last bin. */
export function shotLengthHistogram(lengths: number[], binS = 0.5, capS = 6): Bin[] {
  const binCount = Math.round(capS / binS) + 1;
  const counts = new Array<number>(binCount).fill(0);
  for (const length of lengths) {
    const index = Math.min(Math.floor(Math.max(length, 0) / binS + 1e-9), binCount - 1);
    counts[index] = (counts[index] ?? 0) + 1;
  }
  let last = counts.length - 1;
  while (last > 0 && counts[last] === 0) last -= 1;
  return counts.slice(0, last + 1).map((value, i) => ({
    label: i === binCount - 1 ? `${capS}s+` : `${trim(i * binS)}–${trim((i + 1) * binS)}s`,
    value,
  }));
}

/** One bar per 5-second window of the pacing curve. */
export function pacingBins(cutsPer5s: number[]): Bin[] {
  return cutsPer5s.map((value, i) => ({ label: `${i * 5}–${(i + 1) * 5}s`, value }));
}

export function trim(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function seconds(n: number): string {
  return `${n < 10 ? n.toFixed(1) : Math.round(n)}s`;
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/** "bold_claim" -> "Bold claim" */
export function humanize(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function pacingLabel(medianShotS: number): string {
  if (medianShotS < 1.5) return "Very fast";
  if (medianShotS < 3) return "Fast";
  if (medianShotS < 6) return "Moderate";
  return "Slow";
}
