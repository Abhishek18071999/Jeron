// The paper review page's small decisions (docs/plans/paper-review-v1.md), kept pure so
// `npm test` checks them: which account opens first, how a proposal's status reads, and
// how skipped signals compare with the ones traded.
import type { MissedLine, PaperAccount, Proposal } from "./api.ts";

// The Stocks section's 90+ stocks are paper-traded as this strategy.
export const TOP_SCORE_KEY = "top-score";

export function pickAccount(accounts: PaperAccount[], wanted: string | undefined): PaperAccount | null {
  const byId = accounts.find((a) => String(a.id) === wanted);
  return byId ?? accounts.find((a) => a.strategy_key === TOP_SCORE_KEY) ?? accounts[0] ?? null;
}

export type Tone = "neutral" | "good" | "bad" | "accent" | "warn";

export function proposalTone(status: Proposal["status"]): Tone {
  if (status === "passed backtest") return "good";
  if (status === "failed backtest") return "bad";
  if (status === "could not test") return "warn";
  return "neutral";
}

export function proposalNext(p: Proposal): string {
  if (p.status === "proposed") return "Waiting for its backtest on the history before the paper account (run at the end of the week).";
  if (p.status === "could not test") return p.backtest?.reason ?? "The backtest could not run.";
  if (p.status === "failed backtest") return "Not adopted: it did not beat the strategy on unseen data.";
  return "Ready for a new strategy version: register it in strategies.py, where it is backtested and paper-traded like any other. Jeron never changes a strategy by itself.";
}

export type MissedRow = { reason: string; line: MissedLine; versusTaken: number | null };

// Skipped signals by reason, biggest first, each with its average move minus the traded
// signals' (positive: the skipped ones did better).
export function missedRows(missed: { taken: MissedLine; skipped: Record<string, MissedLine> }): MissedRow[] {
  const taken = missed.taken.avg_move_r;
  return Object.entries(missed.skipped)
    .map(([reason, line]) => ({
      reason,
      line,
      versusTaken: line.avg_move_r !== null && taken !== null ? line.avg_move_r - taken : null,
    }))
    .sort((a, b) => b.line.count - a.line.count || a.reason.localeCompare(b.reason));
}

// "+1.2% vs Nifty 500's +0.4%": both total returns over the same sessions, as fractions.
export function versusBenchmark(own: number | null | undefined, bench: number | null | undefined): string {
  const pct = (x: number) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
  if (own === null || own === undefined) return "-";
  if (bench === null || bench === undefined) return pct(own);
  return `${pct(own)} vs Nifty 500's ${pct(bench)}`;
}
