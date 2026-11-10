import { describe, expect, it } from "vitest";

import { humanize, pacingBins, pacingLabel, percent, seconds, shotLengthHistogram } from "./style-stats";

describe("shotLengthHistogram", () => {
  it("buckets into half-second bins and trims empty tail bins", () => {
    expect(shotLengthHistogram([0.4, 0.5, 0.9, 1.2, 1.2])).toEqual([
      { label: "0–0.5s", value: 1 },
      { label: "0.5–1s", value: 2 },
      { label: "1–1.5s", value: 2 },
    ]);
  });

  it("puts long shots in a capped last bin and keeps every shot", () => {
    const bins = shotLengthHistogram([1, 6, 19, 42]);
    expect(bins.at(-1)).toEqual({ label: "6s+", value: 3 });
    expect(bins.reduce((sum, b) => sum + b.value, 0)).toBe(4);
  });

  it("handles no shots", () => {
    expect(shotLengthHistogram([])).toEqual([{ label: "0–0.5s", value: 0 }]);
  });
});

describe("formatting", () => {
  it("labels pacing windows", () => {
    expect(pacingBins([3, 4])).toEqual([
      { label: "0–5s", value: 3 },
      { label: "5–10s", value: 4 },
    ]);
  });

  it("formats values for people", () => {
    expect([seconds(1.44), seconds(19.02), percent(0.233), humanize("bold_claim")]).toEqual([
      "1.4s",
      "19s",
      "23%",
      "Bold claim",
    ]);
    expect([pacingLabel(1.2), pacingLabel(2), pacingLabel(4), pacingLabel(19)]).toEqual([
      "Very fast",
      "Fast",
      "Moderate",
      "Slow",
    ]);
  });
});
