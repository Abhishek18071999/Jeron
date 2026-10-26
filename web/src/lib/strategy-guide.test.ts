// Strategy guides (src/lib/strategy-guide.ts): every backend strategy has one, and every
// lesson it links to exists. Run with `npm test`.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { GUIDES, howToAct, strategyGuide } from "./strategy-guide.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("every strategy in backend/app/backtest/strategies.py has a guide", () => {
  const keys = [...read("../../../backend/app/backtest/strategies.py").matchAll(/^\s+key="([a-z0-9-]+)",$/gm)].map((m) => m[1]);
  assert.ok(keys.length >= 9, `found ${keys.length} strategy keys`);
  // The combined book has no paper account, so it never signals a stock.
  for (const key of keys.filter((k) => k !== "combined-book")) assert.ok(strategyGuide(key), `no guide for ${key}`);
});

test("keys, versions and -events versions resolve", () => {
  assert.equal(strategyGuide("rs-pullback")?.guide.key, "rs-pullback");
  assert.equal(strategyGuide("rs-pullback-v1")?.guide.key, "rs-pullback");
  const events = strategyGuide("score-swing-events");
  assert.equal(events?.guide.key, "score-swing");
  assert.equal(events?.events, true);
  assert.equal(strategyGuide("no-such-thing"), null);
  assert.equal(strategyGuide(null), null);
});

test("every lesson a guide links to exists", () => {
  const lessons = read("./learn/strategies.ts");
  for (const g of GUIDES) assert.ok(lessons.includes(`slug: "${g.lesson}"`), `no lesson ${g.lesson}`);
  for (const slug of ["signals-and-exits", "how-jeron-tests", "strategy-events-and-combined"]) {
    assert.ok(lessons.includes(`slug: "${slug}"`), `no lesson ${slug}`);
  }
});

test("the steps use the section's rules and the signal's levels", () => {
  const swing = strategyGuide("score-swing")!.guide;
  const steps = howToAct(swing, { zone: "₹300.00 to ₹304.50", stop: "₹282.00", targets: "T1 ₹336.00, T2 ₹354.00" });
  assert.ok(steps.some((s) => s.includes("₹300.00 to ₹304.50")));
  assert.ok(steps.some((s) => s.includes("₹282.00")));
  assert.ok(steps.some((s) => s.includes("+2R, T1 ₹336.00") && s.includes("2 × ATR")));
  assert.ok(steps.some((s) => s.includes("15 sessions")));
  const invest = howToAct(strategyGuide("quality-trend")!.guide);
  assert.ok(invest.some((s) => s.includes("+3R") && s.includes("4 × ATR")));
  assert.ok(invest.some((s) => s.includes("250 sessions")));
  assert.ok(invest.some((s) => s.includes("fund-v1 below 50")));
});
