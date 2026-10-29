// The stock chart's ranges and relative-strength line (src/lib/chart.ts), run with `npm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import type { Candle } from "./api.ts";
import { relativeStrength, sessionsFor } from "./chart.ts";

const candle = (time: string, close: number, nifty500: number | null): Candle => ({
  time,
  open: String(close),
  high: String(close),
  low: String(close),
  close: String(close),
  volume: 1000,
  factor: "1",
  ema50: null,
  ema200: null,
  nifty500,
});

test("ranges never ask for more sessions than there are", () => {
  assert.equal(sessionsFor("3M", 1000), 63);
  assert.equal(sessionsFor("1Y", 120), 120);
  assert.equal(sessionsFor("All", 777), 777);
  assert.equal(sessionsFor("6M", 0), 1);
});

test("relative strength is 100 at the start and follows the ratio", () => {
  const candles = [
    candle("2026-01-01", 100, 1000),
    candle("2026-01-02", 110, 1000), // stock +10%, index flat
    candle("2026-01-05", 110, 1100), // index catches up
    candle("2026-01-06", 121, null), // no index close: left out
  ];
  assert.deepEqual(relativeStrength(candles), [
    { time: "2026-01-01", value: 100 },
    { time: "2026-01-02", value: 110 },
    { time: "2026-01-05", value: 100 },
  ]);
  // From the second bar: rebased there.
  assert.deepEqual(
    relativeStrength(candles, 1).map((p) => p.value),
    [100, 90.91],
  );
  assert.deepEqual(relativeStrength([candle("2026-01-01", 100, null)]), []);
});
