// Compare stocks (src/lib/compare.ts): rows, leads and differences, run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import type { BriefFact, StockBrief } from "./api.ts";
import { checksPassed, compareRows, differences, leaders, parseSymbols } from "./compare.ts";

const fact = (topic: string, label: string, value: string, stance: BriefFact["stance"], number: number | null = null): BriefFact => ({
  id: label,
  topic,
  label,
  value,
  kind: "calculated",
  source: "Jeron scan",
  as_of: "2026-10-23",
  stance,
  number,
});

const brief = (symbol: string, facts: BriefFact[], over: Partial<StockBrief> = {}): StockBrief => ({
  symbol,
  name: null,
  as_of: "2026-10-23",
  stale: false,
  facts,
  why_in_scan: [],
  supporting: [],
  against: [],
  cancels: [],
  scenarios: {},
  checklist: [],
  unknowns: [],
  setup: null,
  strategy: null,
  research_only: null,
  ...over,
});

test("leaders: highest or lowest, ties kept, nothing when equal or alone", () => {
  assert.deepEqual(leaders([80, 75, 15], "higher"), [0]);
  assert.deepEqual(leaders([1, 4.2, 26.1], "lower"), [0]);
  assert.deepEqual(leaders([70, null, 70, 10], "higher"), [0, 2]);
  assert.deepEqual(leaders([50, 50], "higher"), []);
  assert.deepEqual(leaders([50, null], "higher"), []);
  assert.deepEqual(leaders([50, 60], undefined), []);
});

test("rows match by topic, skip what no stock has, and mark the lead", () => {
  const a = brief("AAA", [
    fact("score", "Technical score (tech-v1)", "80.0 / 100", "for", 80),
    fact("momentum", "RSI(14)", "86.7", "against", 86.7),
    // A news headline titled "Results" is not the results date.
    fact("news", "Results", "Financial results, sentiment +1", "for", 1),
  ]);
  const b = brief("BBB", [
    fact("score", "Technical score (tech-v1)", "15.0 / 100", "against", 15),
    fact("momentum", "RSI(14)", "57.7", "for", 57.7),
  ]);
  const groups = compareRows([a, b]);
  assert.deepEqual(
    groups.map((g) => g.title),
    ["Trend and strength", "Momentum, volume and risk"],
  );
  const score = groups[0].rows.find((r) => r.label === "Technical score");
  assert.deepEqual(score?.leads, [0]);
  const rsi = groups[1].rows.find((r) => r.label === "RSI(14)");
  assert.deepEqual(rsi?.leads, [], "RSI has no better direction");
  assert.ok(!groups.some((g) => g.rows.some((r) => r.label === "Results")));
});

test("differences: rows read for one stock and against another", () => {
  const a = brief("AAA", [fact("trend", "200-day EMA", "₹236 (close above)", "for", 236)]);
  const b = brief("BBB", [fact("trend", "200-day EMA", "₹604 (close above)", "for", 604)]);
  const c = brief("CCC", [fact("trend", "200-day EMA", "₹269 (close below)", "against", 269)]);
  assert.deepEqual(differences([a, b, c]), [{ label: "200-day EMA", forSymbols: ["AAA", "BBB"], againstSymbols: ["CCC"] }]);
  assert.deepEqual(differences([a, b]), []);
});

test("checks passed and failed", () => {
  const b = brief("AAA", [], {
    checklist: [
      { label: "Data is current", status: "pass", detail: "", facts: [] },
      { label: "No results within the blackout", status: "fail", detail: "", facts: [] },
      { label: "Size and stop come from the trade plan", status: "unknown", detail: "", facts: [] },
    ],
  });
  assert.deepEqual(checksPassed(b), { passed: 1, total: 3, failed: ["No results within the blackout"] });
});

test("parseSymbols: commas only, names kept whole, no repeats, at most three", () => {
  assert.deepEqual(parseSymbols(" tcs, infy ,TCS,, tata  steel , wipro"), ["TCS", "INFY", "TATA STEEL"]);
  assert.deepEqual(parseSymbols(""), []);
});
