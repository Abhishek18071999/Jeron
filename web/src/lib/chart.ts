// The stock chart's range buttons and its line against the Nifty 500
// (src/app/stocks/[symbol]/chart.tsx). Pure, tested in chart.test.ts.
import type { Candle } from "./api.ts";

export type RangeKey = "3M" | "6M" | "1Y" | "2Y" | "All";

// NSE has about 250 sessions a year.
export const RANGES: { key: RangeKey; sessions: number | null }[] = [
  { key: "3M", sessions: 63 },
  { key: "6M", sessions: 125 },
  { key: "1Y", sessions: 250 },
  { key: "2Y", sessions: 500 },
  { key: "All", sessions: null },
];

export function sessionsFor(range: RangeKey, available: number): number {
  const sessions = RANGES.find((r) => r.key === range)?.sessions ?? available;
  return Math.max(1, Math.min(sessions, available));
}

// The stock's close over the Nifty 500's, 100 at the first bar of the range shown that
// has both: above 100 the stock has done better than the index since then. Bars without
// an index close are left out, not guessed.
export function relativeStrength(candles: Candle[], from = 0): { time: string; value: number }[] {
  const ratios = candles
    .slice(Math.max(0, from))
    .filter((c) => c.nifty500 !== null && c.nifty500 !== undefined && c.nifty500 > 0)
    .map((c) => ({ time: c.time, ratio: Number(c.close) / (c.nifty500 as number) }));
  if (ratios.length === 0) return [];
  const base = ratios[0].ratio;
  return ratios.map((r) => ({ time: r.time, value: Math.round((r.ratio / base) * 10000) / 100 }));
}
