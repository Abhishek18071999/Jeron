// The morning briefing (src/lib/briefing.ts): what to do before the open, run with
// `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import type { Dashboard, Holding, Portfolio } from "./api.ts";
import { briefing } from "./briefing.ts";

const holding = (over: Partial<Holding>): Holding =>
  ({
    entry_id: 1,
    ticker: "AAA",
    shares: 75,
    stop: "100.00",
    action: "hold",
    reason: "stop ₹100.00; T1 ₹108.00",
    problem: null,
    events: [],
    notes: [],
    broker_shares: 75,
    stop_raised_from: null,
    ...over,
  }) as Holding;

const run = (holdings: Holding[]) =>
  briefing(
    { pending: [] } as unknown as Dashboard,
    { stale: false, day: "2026-10-26", holdings, totals: { cash_action: null } } as unknown as Portfolio,
  );

test("a stop raised by the last close is a thing to do before the open", () => {
  const { items, headline } = run([holding({ stop_raised_from: "96.00" })]);
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, "stop");
  assert.equal(items[0].title, "Raise the GTT stop on AAA to ₹100");
  assert.match(items[0].detail, /from ₹96\. Change the GTT to sell 75 sh at a trigger of ₹100\./);
  assert.equal(headline, "1 position to act on before 09:15.");
});

test("an unchanged stop needs nothing", () => {
  const { items, headline } = run([holding({})]);
  assert.deepEqual(items, []);
  assert.equal(headline, "Nothing to do before the open.");
});

test("after booking half, the GTT is for the shares left", () => {
  const { items } = run([holding({ action: "sell half", reason: "T1 ₹108.00 (+2R) reached on 24 Jul: book half", broker_shares: 38 })]);
  assert.equal(items[0].title, "Sell 37 of 75 AAA");
  assert.match(items[0].detail, /Then set the GTT stop to 38 sh at ₹100\.$/);
});
