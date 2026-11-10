import type { ShootPlan } from "@stylecut/schemas";

type Shot = ShootPlan["shots"][number];
type Setup = ShootPlan["setups"][number];

/** Spoken words, counted the same way the API does ("$1,200" and "don't" are one word). */
export function countWords(text: string): number {
  return text.match(/[A-Za-z0-9]+(?:['’.,-][A-Za-z0-9]+)*/g)?.length ?? 0;
}

export type BudgetState = "under" | "ok" | "over";

/** Within ±10% of the budget (or ±5 words for very small budgets) is fine. */
export function budgetState(words: number, budget: number): BudgetState {
  const allowed = Math.max(budget * 0.1, 5);
  if (words > budget + allowed) return "over";
  if (words < budget - allowed) return "under";
  return "ok";
}

export interface SetupGroup {
  setup: Setup | null;
  setupId: string;
  shots: Shot[];
}

/** The shoot checklist: shots in shoot order, grouped by setup in the order setups come up. */
export function groupBySetup(plan: ShootPlan): SetupGroup[] {
  const shots = new Map(plan.shots.map((s) => [s.id, s]));
  const setups = new Map(plan.setups.map((s) => [s.id, s]));
  const groups = new Map<string, SetupGroup>();
  for (const id of plan.shoot_order) {
    const shot = shots.get(id);
    if (shot === undefined) continue;
    let group = groups.get(shot.setup_id);
    if (group === undefined) {
      group = { setup: setups.get(shot.setup_id) ?? null, setupId: shot.setup_id, shots: [] };
      groups.set(shot.setup_id, group);
    }
    group.shots.push(shot);
  }
  return [...groups.values()];
}

/** The lines a shot covers, joined for reading aloud. */
export function spokenText(plan: ShootPlan, shot: Shot): string {
  const lines = new Map(plan.script.map((l) => [l.id, l.text]));
  return (shot.line_ids ?? [])
    .map((id) => lines.get(id) ?? "")
    .filter(Boolean)
    .join(" ");
}

/** How long a teleprompter pass should take. `speed` 1 = the style's pace. */
export function teleprompterMs(text: string, wpm: number, speed: number): number {
  const words = countWords(text);
  if (words === 0 || wpm <= 0 || speed <= 0) return 0;
  return Math.round((words / (wpm * speed)) * 60_000);
}

/** Move one id up (-1) or down (+1). Returns the same array when the move is impossible. */
export function moveItem(ids: string[], id: string, direction: -1 | 1): string[] {
  const from = ids.indexOf(id);
  const to = from + direction;
  if (from < 0 || to < 0 || to >= ids.length) return ids;
  const next = [...ids];
  [next[from], next[to]] = [next[to] as string, next[from] as string];
  return next;
}

/** Marks which words of a line are emphasis words, ignoring case and punctuation. */
export function markEmphasis(text: string, emphasis: string[]): { word: string; strong: boolean }[] {
  const wanted = new Set(emphasis.map((w) => w.toLowerCase().replace(/[^a-z0-9']/g, "")));
  return text
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => ({ word, strong: wanted.has(word.toLowerCase().replace(/[^a-z0-9']/g, "")) }));
}
