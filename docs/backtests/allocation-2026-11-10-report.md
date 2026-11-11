# Allocation study: can the capital around the best strategies be used better? 2026-11-10

Asked for by Abhishek ("discover, build and execute the most profitable realistic strategy
possible"). This is not a new signal and not a new backtest. 68 variants have already been
tried on these ten years, and `residual-momentum-v1` (pre-registered 2026-11-07 for the
same request) had not been run when this was written (it has since been run on Yahoo data,
`yahoo-2026-11-10/`). Another variant picked today would only add a trial.
So this study asks a different question, one the stored runs can answer: the three
strategies that pass section 6 keep more than half their capital idle. Is there a better
use for that capital, or a better way to hold the three together?

**Verdict: no.** Three ideas were checked. Two are risk dials, not edges, and one is too
small to tell from luck. `fip-momentum-v1` on its paper gate is still
the strongest thing Jeron has, and nothing here should change what is paper-traded.

Data: `runs-2026-11-01/equity.json` (runs 1 to 3: each run's daily equity, its cash-sweep
line and Nifty 500), 2019-10-31 to 2026-10-30, 1,739 sessions, after costs, the holdout
year included. Script and its output: `allocation-2026-11-10/`. The only market data
added is Yahoo's Nifty 500 closes for section 3. Every number below is descriptive,
on a period all three strategies were already selected on.

## 1. How much capital is idle

Idle cash, recovered from the cash-sweep line, averages 54% of equity for
`fip-momentum-v1`, 56% for `momentum-v1` and 59% for `rs-pullback-v1`. The cause is the
risk rules, not a lack of signals: 1% risk on a 4 x ATR stop makes each position about 5
to 7% of equity, and the 6% open-risk limit stops new buys at six or seven of them
(`fip-momentum-v1` skipped 1,244 orders for open risk and 1,115 for no free slot).

## 2. A share of idle cash in a Nifty 500 fund: a risk dial

| Share of idle cash in the index | CAGR | Sharpe | Max drawdown | Holdout year |
|---|---|---|---|---|
| 0 (liquid fund, as backtested) | 14.1% | 0.73 | 14.1% | +8.3% |
| 25% | 15.2% | 0.74 | 16.9% | +5.8% |
| 50% | 16.3% | 0.72 | 23.8% | +3.7% |
| 75% | 17.4% | 0.69 | 31.2% | +1.9% |
| 100% (the cash-sweep line) | 18.3% | 0.66 | 38.5% | +0.4% |

`fip-momentum-v1`; the other two look the same (`output.txt`). Nifty 500 itself: 12.4%,
Sharpe 0.39, drawdown 38.3%. Each quarter of idle cash moved adds about one point of
yearly return and about seven points of drawdown above 25%. The Sharpe ratio does not
rise: this buys return with risk at a fair price, as `app/portfolio/calc.py` already says
("an allocation choice, not an edge"). Only the 25% row stays inside the spec's 20%
drawdown limit, and that rests on one crash (March 2020). No switching costs or tax are
counted, so the real figures are a little lower.

## 3. Index only while its trend is up: a better dial, still not an edge

The idea: hold the idle cash in the index only while Nifty 500 ended the last month above
its 200-session average (Faber, "A Quantitative Approach to Tactical Asset Allocation",
2007), to keep the extra return and avoid the index's falls. One rule, no grid, 0.1% of
the amount moved per switch. The stored benchmark starts on 2019-10-31, so the average's
history comes from Yahoo's Nifty 500 closes since 2016 (`nifty500-yahoo.csv`, fetched
with `app/data/http.py`). The rule left the index on 2020-02-28, before most of the March
2020 fall, and switched 13 times in seven years.

| `fip-momentum-v1`, whole period | CAGR | Sharpe | Max drawdown |
|---|---|---|---|
| alone | 14.1% | 0.73 | 14.1% |
| idle cash always in the index | 18.3% | 0.66 | 38.5% |
| half of idle cash always in the index | 16.3% | 0.72 | 23.8% |
| idle cash in the index while the trend is up | 17.1% | 0.72 | 24.1% |
| half of idle cash, while the trend is up | 15.6% | 0.74 | 19.4% |

Read with care:
- The gate cut the cash-sweep line's drawdown from 38.5% to 24.1% and gave up 1.2 points
  of return a year. At the same drawdown as "half, always" it earned 0.8 points more.
  That is the whole benefit, and all of it comes from one event, March 2020.
- From August 2020 on (part a of the output) the gate only cost: about two points a year
  and no smaller drawdown, because the worst stretch came when the strategy's own stocks
  and the index fell together inside a month.
- The Sharpe ratio never rises above the strategy's own (0.72 to 0.74 against 0.73). It
  is a way to take more risk a little more cheaply, not a source of return.
- `momentum-v1` looks the same (17.2%, 23.1%); `rs-pullback-v1` gains less (15.8%, 24.1%).

Not built as a setting. If more return for more drawdown is wanted, "half of idle cash,
only while the index ended last month above its 200-session average" is the only row
that adds return (about 1.5 points a year) and stays under the spec's 20% drawdown limit
for all three strategies. That rests on one crash and counts no tax on the switches (each
exit from the fund within a year is a short-term sale).

## 4. Capital split equally between the passing strategies: too small to tell

| | CAGR | Sharpe | Max drawdown | Holdout year |
|---|---|---|---|---|
| `fip-momentum-v1` alone | 14.1% | 0.73 | 14.1% | +8.3% |
| fip + `rs-pullback-v1` | 13.9% | 0.79 | 12.9% | +5.3% |
| fip + `momentum-v1` | 14.0% | 0.76 | 13.0% | +14.6% |
| all three | 13.9% | 0.80 | 12.3% | +10.3% |

Daily returns correlate 0.58 to 0.70, so a split smooths a little: the same return, a
drawdown about two points lower, a Sharpe ratio 0.07 higher. A paired block bootstrap
puts that difference between -0.29 and +0.50 (95%), above zero in 69% of resamples. That
is not evidence. The split is also an upper bound (daily rebalancing between three
accounts, no costs), and the members were chosen after their results were known.

It is still the sensible way to start with real money, for a reason that needs no
backtest: nobody knows which of the three is the real one (`momentum-v1` held up on Yahoo
data where fip lost its holdout), and a split costs nothing in expected return. Each
keeps its own paper gate. This is a note for the day a strategy reaches "Small capital",
not a new strategy version.

## What this doesn't claim

- Not a new strategy, not a trial against the deflated Sharpe, and no change to any rule,
  setting or status.
- Everything is in-sample in the sense that matters: the three strategies were picked on
  this period. The numbers describe it; they don't predict.
- Idle cash is reconstructed from the cash-sweep line, not read from the engine. The
  rebuilt line ends within 0.2% of the stored one.

## What would add real evidence (all need the install with its data)

1. Run `residual-momentum-v1` once on NSE data, as its plan says:
   `python -m app.cli backtest --strategy residual-momentum`. On Yahoo data it passed all
   seven checks with the best Sharpe of any version (1.27) and a weak holdout
   (`yahoo-2026-11-10/`); the NSE run decides. Done 2026-11-11: 7 of 7, weak evidence,
   no better than `momentum-v1` (`residual-momentum-v1-report.md`).
2. Load the 2025-26 quarterly results (Financial Results CSVs from nseindia.com, on the
   Setup page). `quality-trend-v1` had the best test years of any version (+0.64R, profit
   factor 1.91, positive in all three regimes) and has never traded its holdout because
   the results stop in December 2024. It is untested, not failed, and it is the only
   strong candidate that is not momentum.
3. Keep the paper gate running. Three months and 30 trades of `fip-momentum-v1` on paper
   is worth more than any further search of the same ten years.
