// Compare stocks (/stocks/compare): the rows, grouped, from each stock's brief
// (backend app/explain/facts.py), which stock leads a row where a direction is
// meaningful, and where the stocks disagree. Pure, so `npm test` checks it. Nothing here
// is a verdict: a row's lead says which number is highest or lowest, and why that
// direction matters, not which stock to buy.
import type { BriefFact, Performance, StockBrief } from "./api";

export const MAX_COMPARE = 3; // the backend's limit too (app/api/explain.py)

export type Row = {
  label: string;
  topic: string;
  match: string; // the fact's label starts with this
  help: string;
  lead?: "higher" | "lower"; // the direction Jeron's own rules treat as stronger
  leadText?: string; // the mark on the leading value; default "highest" or "lowest"
  small?: boolean; // long text: shown smaller
  asHeadline?: boolean; // show the fact's label and date (an announcement), not its value
};

export type Group = { title: string; rows: Row[] };

export const GROUPS: Group[] = [
  {
    title: "Trend and strength",
    rows: [
      { label: "Technical score", topic: "score", match: "Technical score", lead: "higher", help: "How many of tech-v1's technical conditions hold, out of 100. 70 or more counts for, under 40 against. A count, not a probability." },
      { label: "Rank in the scan", topic: "score", match: "Rank in the scan", lead: "lower", leadText: "top rank", help: "Its place in the latest scan by technical score; 1 is the highest." },
      { label: "Vs Nifty 500, 3 months", topic: "relative", match: "Return vs Nifty 500, 3 months", lead: "higher", help: "Return over 3 months minus Nifty 500's. Above zero: it beat the market." },
      { label: "Vs Nifty 500, 6 months", topic: "relative", match: "Return vs Nifty 500, 6 months", lead: "higher", help: "Return over 6 months minus Nifty 500's. Several strategies need a top-fifth or top-tenth reading here." },
      { label: "Below the 52-week high", topic: "levels", match: "Below the 52-week high", lead: "lower", leadText: "nearest the high", help: "How far the close is under the highest price of the last year. Within 5% counts for; 25% or more against." },
      { label: "50-day EMA", topic: "trend", match: "50-day EMA", help: "The medium-term trend line. A close above it counts for." },
      { label: "200-day EMA", topic: "trend", match: "200-day EMA", help: "The long-term trend line. A close above it is an uptrend; below it, every Jeron strategy except results-drift and momentum stands aside." },
      { label: "ADX(14)", topic: "trend", match: "ADX(14)", lead: "higher", help: "Trend strength, whichever the direction. Above 20 is a trend; under 20, a range." },
    ],
  },
  {
    title: "Momentum, volume and risk",
    rows: [
      { label: "RSI(14)", topic: "momentum", match: "RSI(14)", help: "Momentum from 0 to 100. 50 to 70 counts for; above 80 is stretched and under 40 weak, both against. No row lead: higher is not simply better." },
      { label: "Volume vs 20-day avg", topic: "volume", match: "Volume vs 20-day average", lead: "higher", help: "The day's volume over its 20-day average. 1.5x or more counts for: buyers are showing up." },
      { label: "ATR(14), daily range", topic: "risk", match: "ATR(14)", help: "The typical day's move as a % of price. A wider range needs a wider stop, so fewer shares for the same risk. Over 6% counts against." },
    ],
  },
  {
    title: "Fundamentals",
    rows: [
      { label: "Fundamental score", topic: "fundamentals", match: "Fundamental score", lead: "higher", help: "fund-v1, from the published quarterly results: growth, margins and P/E against its own history. 60 or more counts for, under 40 against." },
      { label: "Hard reject", topic: "fundamentals", match: "Fundamental hard reject", help: "A problem that scores the company 0 whatever else is true, such as a qualified audit opinion." },
      { label: "Sales growth (TTM)", topic: "fundamentals", match: "Sales growth", lead: "higher", help: "Trailing-twelve-month sales against the year before. Over 10% counts for; shrinking against." },
      { label: "EPS growth (TTM)", topic: "fundamentals", match: "EPS growth", lead: "higher", help: "Trailing-twelve-month earnings per share against the year before." },
      { label: "Net margin (TTM)", topic: "fundamentals", match: "Net margin", lead: "higher", help: "Profit as a share of sales over the last twelve months." },
      { label: "P/E (TTM)", topic: "fundamentals", match: "P/E (TTM)", help: "Price over the last twelve months' earnings. Compare a company with its own past rather than with other industries." },
      { label: "P/E vs its own history", topic: "fundamentals", match: "P/E vs its own history", lead: "lower", leadText: "cheapest for itself", help: "Where today's P/E sits in the company's own history, as a percentile. Under 30% (cheap for it) counts for; over 80% against." },
    ],
  },
  {
    title: "Events",
    rows: [
      { label: "Results", topic: "events", match: "Results", help: "The next results date from NSE's board meetings. Within the blackout (3 sessions before), Jeron's -events strategies take no new entries." },
      { label: "Corporate action ahead", topic: "events", match: "Corporate action ahead", help: "An ex-date coming up: dividend, split or bonus." },
      { label: "Latest announcement", topic: "news", match: "", asHeadline: true, help: "The newest company announcement to NSE in the last 90 days that Jeron counts as material. Green or red only when the news labeller has read it; open the stock for the list." },
    ],
  },
  {
    title: "Signal",
    rows: [
      { label: "Signal", topic: "signal", match: "Signal", help: "The newest signal from a paper-traded strategy. Live: the strategy passed all seven backtest checks. Research only: it didn't, so it is evidence, not a trade." },
      { label: "Entry zone", topic: "signal", match: "Entry zone", help: "Where the strategy would buy, and until when. A buy that opens above the zone is skipped." },
      { label: "Stop", topic: "signal", match: "Stop", help: "Where the idea is wrong. The trade plan sizes the position from the distance to it." },
      { label: "Targets", topic: "signal", match: "Targets", help: "T1 is where half is sold (+2R, +3R long-term). T2 is a reward check, not a sell order." },
      { label: "Strategy's record", topic: "signal", match: "Strategy's out-of-sample record", lead: "higher", leadText: "best expectancy", small: true, help: "The strategy's walk-forward backtest after costs. Expectancy is the average result per trade in R (1R = the risk taken); above 0.15R counts for. The lead compares expectancy." },
      { label: "You hold", topic: "holding", match: "You hold", help: "From your journal." },
    ],
  },
];

export function findFact(b: StockBrief, row: Row): BriefFact | undefined {
  return b.facts.find((f) => f.topic === row.topic && f.label.startsWith(row.match));
}

// The columns whose number leads the row: highest or lowest, ties included. None when
// fewer than two stocks have a number or all are equal.
export function leaders(numbers: (number | null | undefined)[], lead: Row["lead"]): number[] {
  if (!lead) return [];
  const known = numbers.flatMap((n, i) => (n == null || Number.isNaN(n) ? [] : [{ n, i }]));
  if (known.length < 2) return [];
  const best = lead === "higher" ? Math.max(...known.map((k) => k.n)) : Math.min(...known.map((k) => k.n));
  if (known.every((k) => k.n === best)) return [];
  return known.filter((k) => k.n === best).map((k) => k.i);
}

export type ShownRow = Row & { cells: (BriefFact | undefined)[]; leads: number[] };

// The groups with only the rows at least one stock has.
export function compareRows(briefs: StockBrief[]): { title: string; rows: ShownRow[] }[] {
  return GROUPS.map((g) => ({
    title: g.title,
    rows: g.rows
      .map((row) => {
        const cells = briefs.map((b) => findFact(b, row));
        return { ...row, cells, leads: leaders(cells.map((c) => c?.number), row.lead) };
      })
      .filter((row) => row.cells.some(Boolean)),
  })).filter((g) => g.rows.length > 0);
}

export type Difference = { label: string; forSymbols: string[]; againstSymbols: string[] };

// Rows where Jeron's own rules read one stock as for a long trade and another against.
export function differences(briefs: StockBrief[]): Difference[] {
  const out: Difference[] = [];
  for (const g of GROUPS) {
    for (const row of g.rows) {
      const read = briefs.map((b) => ({ symbol: b.symbol, f: findFact(b, row) }));
      const forSymbols = read.filter((r) => r.f?.stance === "for").map((r) => r.symbol);
      const againstSymbols = read.filter((r) => r.f?.stance === "against").map((r) => r.symbol);
      if (forSymbols.length && againstSymbols.length) out.push({ label: row.label, forSymbols, againstSymbols });
    }
  }
  return out;
}

export function checksPassed(b: StockBrief): { passed: number; total: number; failed: string[] } {
  return {
    passed: b.checklist.filter((c) => c.status === "pass").length,
    total: b.checklist.length,
    failed: b.checklist.filter((c) => c.status === "fail").map((c) => c.label),
  };
}

// "TCS, infy , tata steel" -> ["TCS", "INFY", "TATA STEEL"], at most three, no repeats.
export function parseSymbols(text: string, max = MAX_COMPARE): string[] {
  const seen = new Set<string>();
  for (const part of text.split(",")) {
    const s = part.trim().replace(/\s+/g, " ").toUpperCase();
    if (s) seen.add(s);
  }
  return [...seen].slice(0, max);
}

// One colour per stock, the same on its card, chip and chart line.
export const STOCK_COLORS = ["#2563eb", "#ea580c", "#9333ea"];
export const INDEX_COLOR = "#737373";

export type PerfRow = {
  label: string;
  help: string;
  lead: "higher" | "lower";
  leadText: string;
  pick: (p: Performance) => number | null;
  signed?: boolean;
};

export const PERF_ROWS: PerfRow[] = [
  ...(
    [
      ["1M", "1 month", "about 21 sessions"],
      ["3M", "3 months", "about 63 sessions"],
      ["6M", "6 months", "about 126 sessions"],
      ["1Y", "1 year", "252 sessions"],
    ] as const
  ).map(
    ([k, label, sessions]): PerfRow => ({
      label: `Return, ${label}`,
      help: `The price change over the last ${label} (${sessions}), adjusted for splits and bonuses. Dividends are not added. Past returns, not a forecast.`,
      lead: "higher",
      leadText: "highest",
      pick: (p) => p.returns[k],
      signed: true,
    }),
  ),
  {
    label: "Volatility, 1 year",
    help: "How much the price swings: the standard deviation of daily returns over the last year, as a % a year. Lower is calmer; higher needs a wider stop and fewer shares.",
    lead: "lower",
    leadText: "calmest",
    pick: (p) => p.volatility,
  },
  {
    label: "Worst fall, 1 year",
    help: "The biggest drop from a high to a later low within the last year (maximum drawdown). It shows how much pain holding it has involved.",
    lead: "higher",
    leadText: "smallest fall",
    pick: (p) => p.max_drawdown,
    signed: true,
  },
];

// Each row's values for the stocks, then the index (never a lead), and which stock leads.
export function performanceRows(stocks: Performance[], index: Performance | undefined) {
  return PERF_ROWS.map((row) => {
    const values = stocks.map(row.pick);
    return { row, values, index: index ? row.pick(index) : null, leads: leaders(values, row.lead) };
  });
}
