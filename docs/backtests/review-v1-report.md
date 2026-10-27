# Review v1 research: nothing to switch on

Date: 2026-10-26. `python -m app.cli research --trials` on `rs-pullback-v1`, engine
`engine-v3`, prices 2016-01-01 to 2026-10-23 (2,923 stocks), with decision 0017's
demerger and rights adjustment. Options and rules were fixed in
`docs/plans/review-v1.md` before the run. Each row is the full walk-forward: grid
picked on training data with the option on, test years out-of-sample after costs, the
latest 12 months (to 2026-10-23) as holdout. None of this is saved as a backtest run,
and nothing here changes live or paper trading.

**Verdict: no option is adopted.** Two hurt (selling before results, dropping the time
stop). The momentum-crash guard looks much better in the test years but rests on about
46 days in two episodes and did worse in the holdout. The quality filter couldn't be
run here.

## Results

| | Item | Trades | Expectancy | Profit factor | Max DD | CAGR | Sharpe | 2022 | 2024 | Holdout | Checks passed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rs-pullback-v1 as it is | - | 276 | +0.318R | 1.63 | 13.8% | 15.5% | 0.82 | -0.02R (49) | +0.15R (49) | -0.030R (47) | 6 of 7 |
| Sell before results | 4 | 424 | +0.179R | 1.47 | 13.5% | 15.0% | 0.76 | -0.03R (77) | +0.06R (70) | -0.079R (74) | 6 of 7 |
| Halve before results | 4 | 318 | +0.246R | 1.52 | 12.9% | 14.8% | 0.75 | -0.00R (68) | -0.05R (52) | -0.165R (53) | 6 of 7 |
| Momentum-crash guard | 8 | 281 | +0.490R | 1.91 | 10.2% | 22.5% | 1.32 | +0.27R (49) | +0.15R (42) | -0.074R (51) | 6 of 7 |
| No time stop (warn only) | 9 | 322 | +0.173R | 1.19 | 18.2% | 8.8% | 0.26 | -0.11R (71) | -0.16R (84) | -0.019R (49) | 4 of 7 |
| Quality filter | 13 | not run | | | | | | | | | |

Trades in brackets. "Checks passed" are spec section 6's seven.

## Item by item

**4. Holding through results.** Selling (all or half) at the open of the results
session cuts expectancy from 0.32R to 0.18R (all) or 0.25R (half), and both are worse in
the holdout. The trades the strategy holds into results are, on average, the ones
working; selling them gives up the move and pays the round trip again on the
replacement. The results blackout already stops new entries into results; keep it as it
is.

**8. Momentum-crash guard.** The best-looking number here: 0.49R, drawdown 10.2%,
Sharpe 1.32, and 2022 turned from -0.02R to +0.27R. But the guard was on for 65
sessions in ten years, 46 of them in April-July 2020 and April-August 2022. The whole
improvement comes from those two episodes, which is two data points, not a rule. In
the holdout it was on for nine sessions in April-May 2026 and the year came out worse
(-0.074R against -0.030R). This is the classic shape of a fitted filter. It is worth a
pre-registered `rs-pullback-v2` only if the owner wants to paper-trade it beside v1 for
a year; it is not enough to change v1.

**9. Time stop as a warning only.** Clearly worse: 0.17R, profit factor 1.19, drawdown
18.2%, Sharpe 0.26, fails three checks. The 60-session time stop frees capital from
dead trades, and the strategy needs that capital. Keep the hard time stop.

**13. Quality filter.** Not run: it needs fundamentals loaded
(`python -m app.cli fundamentals-import`, or the autopilot's seed results file), and this
machine's database has none. On the owner's install, where results are loaded, the same
command runs it. The review's cash-flow, promoter-pledge and dilution filters need data
that quarterly results don't carry; fund-v1 at 50 or more stands in.

**7. Deflated Sharpe with correlated trials.** `rs-pullback-v1`'s Sharpe deflated against
the 60 variants tried so far is **0.37** counting them as independent, and **0.83**
counting them as the **3.6** independent trials their daily returns are worth (mean
pairwise correlation 0.5, eigenvalue participation ratio). The review was right that
counting all 60 as independent is too harsh; done properly the evidence is much better,
and still short of the 0.95 bar. Reported beside the gates, not a gate.

**10. Missed entries.** In the test years 18 orders were skipped for opening above the
entry zone. Bought at that open anyway, with the same stop and exits, they average
+0.331R (win rate 50%), the same as the +0.334R of the 276 trades taken on the same
basis (after slippage, before charges). Skipping them costs about 18 trades in six years
and changes nothing per trade. Keep engine-v3's rule; the numbers are now in every new
backtest run's summary.

**15. Capacity.** The 1%-of-daily-volume cap would have cut 10% of the trades at ₹1.4
crore of capital, 25% at ₹2.4 crore and 50% at ₹5.3 crore. Far above the plan's capital;
it becomes a real limit only past about ₹1 crore.

Exit reasons for v1 in the test years: stop 138, trailing stop 106, breakeven stop 50,
time stop 27, still open at the end 2.

## Something to watch: v1's own holdout

The holdout is always the latest 12 months, so it has moved since the v2 report (then
to October 2025: +0.022R over 51 trades). Over November 2025 to October 2026, run this
way, `rs-pullback-v1` made **-0.030R over 47 trades**, so it would fail the holdout check
today. This run picks the grid on the training data, the same as `backtest`. The check
that acts on live behaviour is the weekly revalidation (`app/analytics/weekly.py`): it
retires a strategy whose paper (or real) rolling 50-trade expectancy falls below zero,
or whose paper drawdown passes 1.5 times the backtest's. Nothing is changed here; the
owner should look at the paper record on Research > Compare and the next weekly
summary.

## What these numbers can't say

These are five more trials on the same history, on top of the 60 already counted.
An option that looks better on them is a candidate for a new, pre-registered strategy
version that is paper-traded first (spec section 6), never a change to v1. Per the plan,
no option or setting was changed after seeing these results.
