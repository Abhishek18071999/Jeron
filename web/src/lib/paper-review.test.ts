// The paper review page's helpers (src/lib/paper-review.ts), run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import type { PaperAccount, Proposal } from "./api.ts";
import { missedRows, pickAccount, proposalNext, proposalTone, versusBenchmark } from "./paper-review.ts";

const account = (id: number, strategy_key: string) => ({ id, strategy_key }) as PaperAccount;

test("the 90+ account opens first unless another is asked for", () => {
  const accounts = [account(1, "score-swing"), account(2, "top-score"), account(3, "rs-pullback")];
  assert.equal(pickAccount(accounts, undefined)?.id, 2);
  assert.equal(pickAccount(accounts, "3")?.id, 3);
  assert.equal(pickAccount(accounts, "99")?.id, 2);
  assert.equal(pickAccount([account(5, "momentum")], undefined)?.id, 5);
  assert.equal(pickAccount([], undefined), null);
});

test("proposal statuses read plainly", () => {
  const p = (status: Proposal["status"], reason?: string) => ({ status, backtest: reason ? { reason } : null }) as Proposal;
  assert.equal(proposalTone("passed backtest"), "good");
  assert.equal(proposalTone("failed backtest"), "bad");
  assert.equal(proposalTone("proposed"), "neutral");
  assert.match(proposalNext(p("passed backtest")), /never changes a strategy by itself/);
  assert.equal(proposalNext(p("could not test", "too little history")), "too little history");
});

test("skipped signals compare with the traded ones", () => {
  const line = (count: number, avg: number | null) => ({ count, measured: count, avg_move_r: avg, share_up: null });
  const rows = missedRows({
    taken: line(10, 0.2),
    skipped: { "no free position slot": line(30, 0.5), "opened above the entry zone": line(4, null) },
  });
  assert.equal(rows[0].reason, "no free position slot");
  assert.ok(Math.abs((rows[0].versusTaken ?? 0) - 0.3) < 1e-9);
  assert.equal(rows[1].versusTaken, null);
});

test("returns against Nifty 500", () => {
  assert.equal(versusBenchmark(0.012, 0.004), "+1.2% vs Nifty 500's +0.4%");
  assert.equal(versusBenchmark(-0.05, null), "-5.0%");
  assert.equal(versusBenchmark(null, 0.1), "-");
});
