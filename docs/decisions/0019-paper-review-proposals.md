# 0019: The paper review proposes strategy changes; it never makes them

Date: 2026-10-26. Status: proposed (paper-review-v1). Numbered 0019 because 0017 and
0018 are taken by work in other open pull requests.

**Decision.**
1. The Stocks section's 90+ stocks are paper-traded as a new strategy version,
   `top-score-v1` (tech-v1 crossing 90, the swing plan, one grid point), not by changing
   `score-swing-v1`'s settings. Like every strategy it is backtested first and
   paper-traded by the daily replay of stored end-of-day data; nothing is seeded.
2. The paper review groups closed paper trades by what was known at the signal close
   (regime, regime filter, sector, score, ATR %, RSI, volume bands). A fixed rule turns
   a clearly losing group into a proposal, "skip entries where <group>". Proposals are
   stored once, with evidence and time, and never changed.
3. A proposal is tested on data its evidence never saw: a walk-forward backtest, with
   and without the filter, on the history before the paper account opened, plus a
   forward split of the paper trades signalled after it was made.
4. Passing makes a proposal "ready for a new version". A person registers that version
   in code; Jeron never changes a strategy, a score or a risk rule by itself.
5. Paper events (signal, entry, exits, skips) are kept in an append-only audit table
   with the time first recorded, because paper trades themselves are re-derived.

**Why.**
- Spec section 0 rule 7 and the strategy-versioning convention: rules change only as a
  new, backtested version. A self-modifying strategy would make every past result
  unreproducible.
- The evidence for a proposal comes from the paper period, which overlaps the
  backtest's holdout. Testing on the history before the account opened is the only
  data left that the idea hasn't seen; the forward split adds new data as it arrives.
- A fixed rule decided before any result keeps the number of trials known. Every
  tested proposal counts as one.
- Entry filters can be expressed as masks on the market the backtester already uses,
  so they are testable without new engine code. Exit, sizing and risk-control changes
  are shown as observations only.

**Consequences.** Proposals need many closed trades (20 in the group and 20 outside),
so for months there will be none, and that is the honest state. Validation needs about
five years of stored history before an account opened. Grouping paper trades by sector
uses today's NSE industries.
