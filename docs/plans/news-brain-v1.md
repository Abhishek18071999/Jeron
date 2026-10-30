# News brain v1: does the news filter help?

Status: pre-registered on 2026-10-30, before any run on data. Run it once with
`python -m app.cli news-research --cutoff <model cut-off> --out news-brain-v1.md` and keep
the output as `docs/backtests/news-brain-v1-report.md`. It is the news half of M6 part 2's
report ("does the brain help the technical strategies?"), which was never written.

## Why
Jeron pays an LLM to label every NSE announcement (`app/news/`), and the news score from
those labels keeps a stock out of `-events`, `top-score-v1` and `reversal-v1` entries for
about four weeks after bad news. That rule went in on M6's reasoning, not on evidence: no
run has compared the same strategy with and without it. Big funds' use of NLP on news and
filings is the reason to try; it is not evidence that it works on NSE announcements with
Jeron's labels.

## What runs
For `rs-pullback-v1` (the only live-eligible strategy) and `results-drift-v1` (the
strongest research one), each of four arms, every one the full walk-forward with the
grid point picked on training data under that arm's rules (`app/backtest/news_research.py`):

| Arm | News filter (no entry while score < 40) | Results blackout |
|---|---|---|
| Neither rule | off | off |
| News filter | on | off |
| Results blackout | off | on |
| Both | on | on |

Research only: the runs are not saved as backtest runs, so no paper account, signal,
gate or status changes. An arm whose input is missing (no labels, no results calendar)
is reported as not run rather than silently run without the rule.

Two readings beside the table:

1. **Trades by news score.** The Neither-rule run's trades grouped by the news score on
   the signal day: bad news (below 40), none or mixed, good news (above 60). This says
   whether bad news went with worse trades, apart from how the filter reshuffles the
   portfolio (a skipped trade frees a slot for another).
2. **Before and after the model's cut-off.** An LLM labelling a 2020 announcement may
   remember what the stock did next. With `--cutoff` set to the labelling model's
   published training cut-off, every arm's trades are split at that date. Only the
   trades after it are free of that hindsight.

## Decision rule (fixed now)
The news filter **helps** a strategy only if, against Neither rule, all of these hold:

- test-period expectancy at least 0.03R higher, and profit factor not lower;
- holdout expectancy not lower;
- in the trades from the cut-off on, expectancy not lower;
- in the Neither-rule run, bad-news trades average below the no-news trades.

The results blackout is judged the same way, without the cut-off and bucket conditions.

If it helps: register a new strategy version with it by hand (for example
`rs-pullback-news-v1`), paper-trade it first; nothing live changes because of this run.
If it does not: say so in the report, keep the existing versions as they are (versions
never change), and consider labelling only what the stock page and Explain need, since
the score would then be paying for nothing in the strategies.

Either way these are 6 more trials (3 arms on each of 2 strategies), to count in the
next deflated Sharpe.

The good-news bucket is reporting only. A "buy on good news" tilt would be a new idea
with its own plan.

## Known limits, written down now
- Labels cover only the years `news-label` has been run for; the report states the
  covered years, and in an unlabelled year the filter does nothing.
- Subject-rule labels carry no sentiment, so there is no LLM-free score to compare with.
  The cut-off split is the hindsight check instead.
- With about 300 trades a strategy, a 0.03R difference is within noise. A pass is a
  reason to paper-trade, not proof.
