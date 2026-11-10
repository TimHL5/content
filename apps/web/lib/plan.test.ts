import type { ShootPlan } from "@stylecut/schemas";
import { describe, expect, it } from "vitest";

import { budgetState, countWords, groupBySetup, markEmphasis, moveItem, spokenText, teleprompterMs } from "./plan";

const shot = (id: string, setup: string, lines: string[] = []) =>
  ({ id, setup_id: setup, line_ids: lines }) as ShootPlan["shots"][number];

const plan = {
  script: [
    { id: "L1", text: "Stop wasting money." },
    { id: "L2", text: "Negotiate first." },
  ],
  shots: [shot("S1", "desk", ["L1"]), shot("S2", "table"), shot("S3", "desk", ["L1", "L2"]), shot("S4", "street")],
  setups: [{ id: "desk", location: "home office" }, { id: "table", location: "kitchen" }],
  shoot_order: ["S3", "S1", "S2", "S4", "S99"],
} as unknown as ShootPlan;

describe("countWords", () => {
  it("matches the API's counting", () => {
    expect(countWords("It's $1,200 a month, don't sign yet!")).toBe(7);
    expect(countWords("  spaced   out \n words ")).toBe(3);
    expect(countWords("")).toBe(0);
  });
});

describe("budgetState", () => {
  it("allows ±10%, or ±5 words on small budgets", () => {
    expect([budgetState(100, 100), budgetState(110, 100), budgetState(111, 100), budgetState(89, 100)]).toEqual([
      "ok",
      "ok",
      "over",
      "under",
    ]);
    expect([budgetState(45, 40), budgetState(46, 40), budgetState(34, 40)]).toEqual(["ok", "over", "under"]);
  });
});

describe("groupBySetup", () => {
  it("follows shoot order and tolerates unknown setups and shots", () => {
    const groups = groupBySetup(plan);
    expect(groups.map((g) => [g.setupId, g.shots.map((s) => s.id)])).toEqual([
      ["desk", ["S3", "S1"]],
      ["table", ["S2"]],
      ["street", ["S4"]],
    ]);
    expect(groups[0]?.setup?.location).toBe("home office");
    expect(groups[2]?.setup).toBeNull();
  });
});

describe("teleprompter helpers", () => {
  it("joins a shot's lines and times the scroll", () => {
    expect(spokenText(plan, plan.shots[2] as ShootPlan["shots"][number])).toBe("Stop wasting money. Negotiate first.");
    expect(spokenText(plan, plan.shots[1] as ShootPlan["shots"][number])).toBe("");
    expect(teleprompterMs("one two three", 180, 1)).toBe(1000);
    expect(teleprompterMs("one two three", 180, 0.5)).toBe(2000);
    expect(teleprompterMs("", 180, 1)).toBe(0);
  });

  it("marks emphasis words regardless of case and punctuation", () => {
    expect(markEmphasis("Stop wasting money, now!", ["WASTING", "money"])).toEqual([
      { word: "Stop", strong: false },
      { word: "wasting", strong: true },
      { word: "money,", strong: true },
      { word: "now!", strong: false },
    ]);
  });
});

describe("moveItem", () => {
  it("moves within bounds and is a no-op otherwise", () => {
    const ids = ["a", "b", "c"];
    expect(moveItem(ids, "b", -1)).toEqual(["b", "a", "c"]);
    expect(moveItem(ids, "b", 1)).toEqual(["a", "c", "b"]);
    expect(moveItem(ids, "a", -1)).toBe(ids);
    expect(moveItem(ids, "c", 1)).toBe(ids);
    expect(moveItem(ids, "zz", 1)).toBe(ids);
  });
});
