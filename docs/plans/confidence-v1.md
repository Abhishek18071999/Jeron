# Confidence engine, strategy status and the degradation monitor (confidence-v1)

From the 2026-10 external review of the project document. Its warning: rs-pullback-v1
passed all seven gates, yet its holdout expectancy was +0.022R, its holdout profit factor
0.96 and its deflated Sharpe 0.39 against 52 versions tried. Passing the gates is not
evidence of a dependable edge. This milestone adds the layer that says how strong the
evidence is, makes every strategy's status visible, and watches paper results against
the backtest without mistaking variance for decay.

Live behaviour is unchanged: no strategy version, gate, signal or paper account trades
differently. The one stricter rule: a retired version can paper-trade again only after a
recorded revalidation (before, `paper --restart` reopened it silently).

## The review, point by point, against the code

| Review point | Already in Jeron | This milestone | Elsewhere / not built |
|---|---|---|---|
| 1. Confidence intervals, bootstrap, Monte Carlo | Bootstrap "expected range" for paper vs backtest (`compare.py`), deflated Sharpe | 95% intervals for expectancy, profit factor, win rate; block bootstrap of the curve (drawdown, CAGR); Monte Carlo of trade order (losing streak, R drawdown) | |
| 1. Sensitivity to slippage, costs, entry timing, parameters | | Re-runs with slippage x2, charges x1.5, entries one session late; every grid point traded alone | Effective-trials deflated Sharpe: PR #38 (`research.py`) |
| 1. Track every variant, including discarded | Every grid point of every run logged (`backtest_variants`) | Registry of every version in the code or in a stored run, with the total parameter sets tried | |
| 1. Dependence on one year, sector, a few trades | By-year and by-regime tables | Without the 5 best trades, without the best year, best sector's share of the gains | Sectors are today's, not point in time (noted on the report) |
| 1. Evidence rating separate from the gates | | `strong / moderate / weak / insufficient`, thresholds fixed below | |
| 2. Portfolio-level realism | Cash at fill time, competing signals ranked by score, slots, heat, gaps through stops, circuit locks (stop fills next open), volume cap 1% of ADV, slippage by turnover, sector cap and correlation (paper), tax estimate | Golden tests for competing orders and cash-limited partial fills; gross-to-net breakdown (before slippage, slippage, charges, dividends) | Slippage that scales with order size against volume, sector exposure through time (no point-in-time sectors): not built |
| 3. Adaptive capital allocation | Hard limits: heat, drawdown brake, sector cap, guardrails | | Not built: allocation by evidence needs a proven strategy first (P2) |
| 4. Degradation monitor | Weekly revalidation (rolling 50-trade expectancy, drawdown), 20-trade early warning | Paper placed in the backtest's distribution for that many trades: too early / on track / ordinary variance / watch / deteriorating; signal frequency, loss size, sector flags; the 50-trade rule's false-retirement rate; revalidation required to resume | Real-vs-paper slippage stays on Compare (`divergence`) |
| 5. Data integrity, snapshots | Raw prices kept, two-source cross-check, quality report blocks the scan, stale-data guard, market fingerprint | Fingerprint now covers corporate-action factors, dividends, liquidity, bands and the later brains; every run records code hash, settings hash and last data date | Rights issues, demergers, dead-man's switch, stale entries: PR #38 |
| Strategy status everywhere | Stages on Compare (research only / paper / small real / full capital) | Research / Paper / Small capital / Approved / Retired with date, reason and who set it; only the owner can promote, past the checks below | |
| 5 (Today). Decisions first | Morning briefing, signals, risk, mood, behind the scenes | Market regime, heat, candidates and data status first; status and evidence on every live signal; Strategy health card; System health | |
| P0 "merge auth, backups, settings" | In main: web login with TOTP, nightly backups with the weekly restore check, the Settings page | | Restore drill runbook: PR #38 |
| P2/P3 (fundamentals, news evaluation, research lab, what-if, coach, AI assistant) | Partly built (fund-v1, news eval, explain) | | Later milestones |

## Confidence engine (`app/backtest/confidence.py`, pure)

Computed for every new run and stored in `summary.confidence` (no migration):

- intervals: 2,000 bootstrap resamples (seed fixed, so a rerun gives the same numbers),
  percentile method, 95%;
- curve: moving-block bootstrap of daily returns, 20-session blocks;
- order risk: the trades resampled into new orders; median and 95th percentile of the
  longest losing streak and the R drawdown;
- concentration and robustness as in the table.

Evidence rating, fixed before any rating was seen:

| Check | Pass |
|---|---|
| sample | at least 100 out-of-sample trades |
| expectancy_ci | 95% interval of expectancy above 0R |
| profit_factor_ci | 95% interval of profit factor above 1 |
| holdout | at least 20 trades, expectancy above 0, profit factor above 1 |
| deflated_sharpe | at least 0.95 |
| scenario:slippage, charges, late | expectancy still above 0 |
| grid | at least 2/3 of the grid points positive on their own |
| without_top, without_best_year | expectancy still above 0 |
| sector | no sector more than 50% of the gains (when sectors are known) |

Insufficient: under 30 trades. Strong: every check passes. Moderate: the expectancy
interval and the holdout pass and at most 2 others fail. Weak: anything else.

The three re-runs cost three more simulations per backtest. The autopilot backtests once
more any paper-traded version whose newest run has no rating, so the existing accounts
get one without a command.

## Strategy status (decision 0018)

Table `strategy_status_changes` (append-only). Jeron derives Research, Paper and Retired;
I set Small capital or Approved with `strategy-status VERSION STATUS --reason`, refused
unless:

- Small capital: the paper gate passed and the evidence is moderate or strong;
- Approved: Small capital first, and the real gate passed;
- Paper after a retirement: a backtest run made after the retirement passes the gates.

The status is shown on Today (each live signal and the Strategy health card), the
backtest page, and Research > Strategies and evidence. It changes nothing the engine or
the signals do.

## Degradation monitor (`app/analytics/health.py`, pure)

Paper's average R as a percentile of averages of that many backtest trades (2,000 draws):
under 10 trades too early; 20th percentile or above on track; 5th-20th ordinary variance;
below the 5th watch (under 30 trades) or deteriorating (30 or more). Flags: entries
outside 0.5x-2x the backtest's rate after 40 sessions, average loss 0.3R worse than the
backtest's, over 40% of trades in one sector. Shown on Today, in `/strategies` and in the
weekly summary (STRATEGY HEALTH).

`false_retirement`: the share of 200-trade paths drawn from the backtest in which some
rolling 50-trade average falls below 0, i.e. how often the current revalidation rule
retires a strategy that is exactly as good as its backtest. On +0.5R trades with a 1.5R
spread it is about 13%; on a thin +0.12R edge about 88%. The rule is spec section 6's and
is not changed here: whether to replace it with the distribution-based verdict is a
decision for Abhishek.

## Provenance

`summary.provenance`: hash of the backend's source files (works in the Docker image),
`JERON_GIT_SHA` when set, the market fingerprint and last data date, and a hash of the
portfolio rules, costs, gates, engine version, strategy version and schedule.

## Tests

`test_confidence.py` (intervals, block bootstrap, order risk, concentration, rating,
scaled costs, late entries, the walk-forward's summary), `test_strategy_health.py`
(verdicts, flags, false retirement, status rules), `test_strategies_db.py` (status,
promotion, retirement and revalidation, API, registry), and two engine golden tests
(competing orders, cash-limited partial fill).

## Acceptance

- A new backtest run shows its evidence rating, intervals and re-runs on its page.
- `strategy-status` lists every version; promotion is refused without the evidence.
- Today shows the decision strip, status and evidence on live signals, and Strategy health.
- Backend and web checks pass; existing golden trades unchanged.
