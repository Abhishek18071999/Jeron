// How to use each strategy's signal, in plain words: what it looks for, which section it
// trades in, when it tends to work, and what to do with a signal. Shown beside a signal on
// the stock page and on Compare, with a link to the Learn lesson. The rules mirror
// backend/app/backtest/strategies.py (entry rules, `TIERS`) and engine.py (the trade
// around every entry); a change there should change this file and the lessons in
// src/lib/learn/strategies.ts.

export type Section = "swing" | "positional" | "invest";

export type StrategyGuide = {
  key: string; // the strategy key without "-events": "rs-pullback"
  name: string;
  section: Section;
  lookFor: string; // the entry rule, one sentence
  works: string; // when it tends to work, and when it doesn't
  watch: string; // the one thing to keep an eye on
  exit?: string; // a strategy's own exit rule, on top of the stop, T1 and the trail
  lesson: string; // slug under /learn
};

// The trade around every entry, by section (TIERS in strategies.py).
export const SECTION_RULES: Record<
  Section,
  { label: string; href: string; hold: string; t1R: number; trailAtr: number; timeStop: number }
> = {
  swing: { label: "Swing", href: "/trade/swing", hold: "days to about three weeks", t1R: 2, trailAtr: 2, timeStop: 15 },
  positional: { label: "Positional", href: "/trade/positional", hold: "weeks to about three months", t1R: 2, trailAtr: 2, timeStop: 60 },
  invest: { label: "Long-term", href: "/trade/invest", hold: "months to a year or more", t1R: 3, trailAtr: 4, timeStop: 250 },
};

export const GUIDES: StrategyGuide[] = [
  {
    key: "rs-pullback",
    name: "RS leader pullback to the 20-day EMA",
    section: "positional",
    lookFor:
      "A stock in the top 10% for 6-month strength against Nifty 500, in an uptrend (close above the 50-day EMA, 50-day above the 200-day), whose day's low touched the 20-day EMA and whose close held above it.",
    works: "Strong markets and sideways ones: leaders that dip and hold tend to resume. It stands aside when the market regime is bear.",
    watch: "A close back below the 20-day EMA after the signal means the dip did not hold.",
    lesson: "strategy-rs-pullback",
  },
  {
    key: "results-drift",
    name: "Drift after strong results",
    section: "positional",
    lookFor:
      "The session after a results board meeting, when the stock beat Nifty 500 by at least 5% since the close before results, on at least 2x its 20-day average volume.",
    works: "Around results season, in any market: a big, heavy-volume reaction to results tends to keep drifting. No trend or regime filter.",
    watch: "The stop sits near the pre-results price: if the whole reaction reverses, the idea was wrong. Its holdout year was negative.",
    lesson: "strategy-results-drift",
  },
  {
    key: "sector-rotation",
    name: "10-week high in a leading sector",
    section: "positional",
    lookFor:
      "A close above the highest high of the previous 50 sessions, in an uptrend, when the stock's sector is among the 3 strongest of ten NSE sectoral indices over 3 months.",
    works: "When money is rotating into a few sectors and the market is not in a bear regime.",
    watch: "Sector leadership changes: check the sector strength on Stocks before you buy.",
    lesson: "strategy-sector-rotation",
  },
  {
    key: "trend-breakout",
    name: "52-week breakout by an RS leader",
    section: "positional",
    lookFor:
      "A close above the prior 52-week high on at least 1.5x average volume, by a stock in the top 20% for 6-month strength, in an uptrend, with the market regime bull.",
    works: "Bull markets only, when new highs are being bought rather than sold.",
    watch: "Breakouts often dip back to the breakout level first, so the stop is wide (3 ATR) and the share count small.",
    lesson: "strategy-breakouts",
  },
  {
    key: "breakout-52w",
    name: "52-week-high breakout with volume",
    section: "positional",
    lookFor: "A close above the prior 52-week high on at least 1.5x average volume, with the close above the 200-day EMA.",
    works: "Trending markets. Without a strength or regime filter it also catches breakouts that fail.",
    watch: "A close back under the old 52-week high is the first sign the breakout failed.",
    lesson: "strategy-breakouts",
  },
  {
    key: "score-swing",
    name: "Technical score crossing",
    section: "swing",
    lookFor: "The tech-v1 score closing at or above 80 after being below it the day before (85 when the regime filter is on).",
    works: "Broad uptrends, when many technical conditions line up at once. Short holds.",
    watch: "A high score can come with an RSI above 80: stretched, and more likely to pull back first.",
    lesson: "strategy-score-swing",
  },
  {
    key: "top-score",
    name: "Top technical score (90+)",
    section: "swing",
    lookFor:
      "The tech-v1 score closing at or above 90 after being below it the day before: the Stocks section's 90+ stocks, on the day they get there. Not around results or after bad news.",
    works: "Strong, broad uptrends where almost every technical condition lines up at once. Short holds.",
    watch: "A 90+ score nearly always comes on a big up day, so the open can be above the entry zone; then the signal is skipped.",
    lesson: "strategy-score-swing",
  },
  {
    key: "pullback-trend",
    name: "Pullback in an uptrend",
    section: "swing",
    lookFor:
      "An uptrend (close above the 200-day EMA, 20-day above the 50-day, ADX above 20) where RSI(14) closes back above 40 after dipping below it.",
    works: "Steady trends with orderly dips. It struggles in choppy, trendless markets.",
    watch: "If RSI turns down again below 40 soon after, the dip is becoming a downtrend.",
    lesson: "strategy-pullback-trend",
  },
  {
    key: "quality-trend",
    name: "Strong results in a long-term uptrend",
    section: "invest",
    lookFor:
      "The first day a company's fundamental score (fund-v1, from published results) is at least 70 while the close is above the 50-day EMA and the 50-day is above the 200-day.",
    works: "Good businesses in established uptrends, held for months. No market-regime filter.",
    watch: "Each new quarterly result: the score is re-checked when results are filed.",
    exit: "Sold at the next open after a new results filing takes fund-v1 below 50.",
    lesson: "strategy-quality-trend",
  },
  {
    key: "momentum",
    name: "Monthly momentum leaders",
    section: "invest",
    lookFor:
      "On the first session of each month, a stock in the top 10% of the universe for 12-1 momentum (the return from a year ago to a month ago, divided by its volatility).",
    works: "Markets where leaders keep leading. It can give back a lot in sharp reversals, when laggards suddenly lead.",
    watch: "The rank on the first session of each month.",
    exit: "Sold at the next open after the first session of a month on which its momentum rank is below 0.75.",
    lesson: "strategy-momentum",
  },
];

const BY_KEY = new Map(GUIDES.map((g) => [g.key, g]));

// "rs-pullback", "score-swing-events" or a version ("rs-pullback-v1") -> its guide.
export function strategyGuide(strategy: string | null | undefined): { guide: StrategyGuide; events: boolean } | null {
  if (!strategy) return null;
  let key = strategy.trim().toLowerCase().replace(/-v\d+$/, "");
  const events = key.endsWith("-events");
  if (events) key = key.slice(0, -"-events".length);
  const guide = BY_KEY.get(key);
  return guide ? { guide, events } : null;
}

export const EVENTS_RULE =
  "This is the \"-events\" version: it also skips entries within 3 sessions of results and after bad news (news score below 40).";

// What to do with a signal from this strategy, step by step. Levels come from the
// signal when known.
export function howToAct(
  guide: StrategyGuide,
  levels: { zone?: string; stop?: string; targets?: string } = {},
): string[] {
  const r = SECTION_RULES[guide.section];
  const steps = [
    "Check the setup is still valid: no trade at or below the stop, and the entry zone not expired.",
    "Open the trade plan: it sizes the position so the stop risks your set % of capital, and checks heat, sector and position limits.",
    `Before the open (9:00 to 9:07), place a limit buy at the top of the entry zone${levels.zone ? ` (${levels.zone})` : ""}. If it opens above the zone, skip it: don't chase.`,
    `Once filled, set the stop at your broker as a GTT${levels.stop ? ` (${levels.stop})` : ""}.`,
    `At a close of +1R, move the stop to your entry. At T1 (+${r.t1R}R${levels.targets ? `, ${levels.targets.split(",")[0]}` : ""}) sell half; the rest trails ${r.trailAtr} × ATR below the highest close.`,
    `If it never closes at +1R within ${r.timeStop} sessions, sell at the next open (time stop).`,
  ];
  if (guide.exit) steps.push(guide.exit);
  return steps;
}
