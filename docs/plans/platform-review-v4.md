# Platform review v4 (2026-11-05)

A review of `main` at `4a4bc9f` (PR #46) against the owner's "make it the best version"
brief, building on `platform-audit-v1`, `platform-review-v3` and the shared
`remaining-work.md` instead of repeating them. The full findings and the target
architecture are in the review document shared in the project thread; this file is the
plan for the code on this branch.

## Fixed on this branch (real money first)

1. **The real trade plan sized on the starting capital, the engine on equity.**
   `app/plan/calc.py` passed `JERON_CAPITAL` to `position_size`, while the engine (and so
   the backtest, paper trading and the signals) passes the account's equity. After a 10%
   loss the real plan still risked 1% of the old capital, about 1.11% of what is left,
   and after gains it under-sized; the real account drifted from the rules it is
   compared against. Now: with the journal account known, the plan sizes on
   `AccountState.equity` (capital + realised + open P&L), the same rule as the engine.
   The heat and sector percentages stay on `JERON_CAPITAL` as before (follow-up below).
2. **The real trade plan could spend money the account doesn't have.** The engine cuts
   a buy to the cash left ("not enough cash"); the plan had no cash check, so six
   positions near the 20% cap (heat allows it) planned about 120% of the capital. Now
   `AccountState.cash` (capital + realised - open positions at cost) caps the size, buy
   charges included, with a warning when cash cut it and a failing size check when no
   share is affordable.
3. **Long-term capital gains were dated by a day count.** Listed shares are long-term
   when held *more than 12 months*; the code used "more than 365 days", which across a
   29 February calls the anniversary itself long-term (bought 1 Mar 2023, sold
   1 Mar 2024: 366 days, still short-term). The tax note would then tell the owner to
   sell a day early, at 20% instead of 12.5% and without the exemption. Now
   `costs.long_term_from` / `is_long_term` count by the calendar; journal sales carry
   their lot's buy date, and the tax notes date the mark from it.

Tests: `test_real_plan_sizes_on_equity`, `test_real_plan_never_spends_more_than_the_cash`,
`test_account_cash_from_the_journal` (listed in `tests/test_risk_rules.py`), and three
calendar tests in `tests/test_portfolio_calc.py`.

## Not changed, on purpose

- The backtest's tax estimate (`costs.estimate_tax`) keeps its day count: it is an
  estimate beside the gates, and changing it would change stored runs' numbers. The
  error is one day in four years per trade.
- No strategy, score or engine rule changed, so no new version and no re-run.

## Follow-ups (not built here)

- Heat and sector % in the plan, and the Portfolio page, against equity rather than
  `JERON_CAPITAL` (the engine's denominators), in one change so the two pages agree.
- Tax notes use a position's first buy date for every lot; a lot added later turns
  long-term later.
- Make `JERON_API_TOKEN` required outside development (generate one on first start).
- `PUT /imports/{name}` reads the whole body before the size check; stream it.
