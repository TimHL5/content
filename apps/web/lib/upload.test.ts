import { describe, expect, it } from "vitest";

import { planParts, referenceFileProblem, REFERENCE_MAX_BYTES } from "./upload";

describe("planParts", () => {
  it("splits into contiguous ranges that cover the file exactly", () => {
    expect(planParts(20, 8)).toEqual([
      { partNumber: 1, start: 0, end: 8 },
      { partNumber: 2, start: 8, end: 16 },
      { partNumber: 3, start: 16, end: 20 },
    ]);
  });

  it("uses one part for small files and none for empty ones", () => {
    expect(planParts(5, 8)).toEqual([{ partNumber: 1, start: 0, end: 5 }]);
    expect(planParts(8, 8)).toHaveLength(1);
    expect(planParts(0, 8)).toEqual([]);
    expect(planParts(8, 0)).toEqual([]);
  });
});

describe("referenceFileProblem", () => {
  it("accepts supported video files regardless of case", () => {
    expect(referenceFileProblem({ name: "Clip.MP4", size: 1000 })).toBeNull();
    expect(referenceFileProblem({ name: "phone.mov", size: REFERENCE_MAX_BYTES })).toBeNull();
  });

  it("explains what is wrong otherwise", () => {
    expect(referenceFileProblem({ name: "song.mp3", size: 1000 })?.message).toMatch(/type/);
    expect(referenceFileProblem({ name: "big.mp4", size: REFERENCE_MAX_BYTES + 1 })?.message).toMatch(/200 MB/);
    expect(referenceFileProblem({ name: "empty.mp4", size: 0 })?.message).toMatch(/empty/);
  });
});
