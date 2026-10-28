# Section 20: Post-review hardening plan

Date: 2026-10-28. The second outside review of Jeron (Abhishek pasted it on 2026-10-28;
the first, 15-point review is `docs/plans/review-v1.md`). Its verdict, in one line:
"your engineering discipline is ahead of your edge". This page tracks each of its
points: what was already done, what this plan built, and what is waiting for whom.
It sits beside the milestones in spec section 11 and is updated when an item moves.

Each point was checked against the code first. The project's own rules still hold: no
strategy version changes after its results are seen, a new idea is a new pre-registered
version, and nothing goes live without passing spec section 6 and then paper trading
(decision 0018's ladder).

## Status at a glance

| # | Item | Status | Where |
|---|---|---|---|
| R1 | Fix demerger and rights adjustment | Done (2026-10-26, PR #38) | decision 0017 |
| R2 | Morning entry re-validation | Done (2026-10-26, PR #38) | `app/exits/job.py` `entry_checks` |
| R3 | Momentum-crash guard | Tested, not adopted | `docs/backtests/review-v1-report.md` |
| R4 | Quality filter on rs-pullback | Built, not yet run: needs your results data | `app/backtest/research.py` `quality` |
| R5 | A second, uncorrelated strategy family | Pre-registered and built; runs once on your install | `docs/plans/reversal-v1.md` |
| B | Paper first in a drawdown over 10%, journal before trading | Built (this plan) | `app/plan/calc.py`, alerts |
| P | Idea-first research instead of parameter search | Adopted as a rule (below) | this page |

## The review's worries, in its order

**1. One correlated edge.** True. Every live-eligible version is relative-strength
momentum, and the research strategies that came closest (trend-breakout, sector
rotation, momentum) are the same family: their daily returns correlate 0.5 or more with
rs-pullback's. The closest thing to a second family, `results-drift-v1` (post-earnings
drift, a documented anomaly), passed 6 of 7 checks and failed its holdout (-0.33R over
34 trades), so it stays research only. The answer here is R5.

**2. The 19:00 signal to 09:15 execution gap.** Done before this review (R2). The 08:30
pre-open check lists **BUYS AT THE OPEN**: each live signal valid today is re-planned on
the real account (heat, positions, drawdown, loss limits, sector, results blackout, kill
switch, and now the paper-first rule), one after another so two buys can't pass limits
together that each passes alone; it skips a stock held by quality check #9 or with a
split, bonus, rights or demerger ex-date today. The limit stays as written in
review-v1: Jeron has end-of-day data only, so at 08:30 it knows nothing about the open
that it didn't know at 19:00. Gaps and circuits are checked by you at 09:08 (the alert
says how) until a broker feed is chosen (spec section 2, still your decision).

**3. Behavioural risk.** Built here (item B). Spec section 5 already halved risk at 10%
below the peak and paused new entries at 15%, but between the two a trade was one tick
away. Now, from 10% (`JERON_DRAWDOWN_JOURNAL_PCT`, on the Settings page; 0 turns it off):
- every live signal alert and the daily summary open with **PAPER ONLY: your account is
  X% below its peak**;
- the trade plan can't be saved without a **drawdown note** of at least 20 words: why
  this trade, why now, and what you'll do if it fails. It is a hard check, whatever
  `JERON_RISK_LIMITS_BLOCK` says, and is stored with the plan (`details.drawdown_note`),
  which the journal entry points to by `plan_id`;
- the pre-open BUYS AT THE OPEN list doesn't list such a signal as a buy, saying why;
- paper accounts are untouched: they keep trading every signal, which is the "paper
  only" record to compare against.
The weekly report already measures your deviations from the signals; the notes make the
reasoning behind a drawdown trade reviewable later. Test:
`tests/test_risk_rules.py::test_real_drawdown_paper_first_needs_a_note`.

**4. Unadjusted corporate actions corrupting RS ranks.** Done before this review (R1),
decision 0017. Rights issues are adjusted by the theoretical ex-rights price, demergers
by the ex-date's special pre-open price. Not everything can be: a rights issue whose text
gives only the premium is adjusted only when the unknown face value moves the factor by
0.5% or less (45 of 267 since 2016). The rest are caught by quality check #9 (a fall of
over 15% with no split or bonus): the stock's signals are sent HELD and its exits go to
CHECK BY HAND, so an unexplained drop can't silently become a signal.

## The roadmap, item by item

**R1, R2.** Done, above.

**R3. Momentum-crash guard.** Run in review-v1 as a pre-registered research option (no
new entries while Nifty 500 is up 8% or more over 20 sessions after being below its
200-day EMA in the last 60; Daniel and Moskowitz 2016). It looked best of all (0.49R
against 0.32R, Sharpe 1.32 against 0.82) but the whole gain came from 46 sessions in two
episodes, 2020 and 2022, and it did worse in the holdout (-0.074R against -0.030R). Two
episodes are two data points, not a rule, so **v1 is not changed**. It could still
become a pre-registered `rs-pullback-v2` paper-traded beside v1, but that is one more
momentum variant, which is what point P argues against; it is not built unless you ask.

**R4. Quality filter on rs-pullback.** The option exists (enter only when fund-v1 is 50
or more where known) but has never been run: the machine that ran review-v1 had no
quarterly results. Your install has them once `nse-results-2016-2026.zip` is imported
(the autopilot does it). To run it:
`python -m app.cli research --option quality --trials --out quality.md`. Whatever it
shows, the result can only become a pre-registered `rs-pullback-v2` to paper-trade
beside v1; it can't change v1. Known gap: results from January 2025 onward are thin in
the seed file, so the holdout year is the weakest part of this test.

**R5. A second, uncorrelated strategy family.** `reversal-v1`, short-term reversal of
no-news losers (Jegadeesh 1990, Lehmann 1990; Chan 2003 for why news matters). It buys
the 10% of the universe that fell most over 5 sessions when no results or bad news
explain the fall, and sells once the fall is made up against the universe. One grid
point, rules committed before the code and before any data
(`docs/plans/reversal-v1.md`). It buys weakness where everything else buys strength, so
it is the first candidate that could be uncorrelated; its correlation with rs-pullback
is reported, not assumed. The review said "only after paper trading": the run itself
only says whether it is worth paper trading. Even if it passes all seven checks, it
reaches real money only through the ladder (paper gate of 3 months and 30 trades, a
moderate or strong evidence rating, your `strategy-status` call). The autopilot runs its
backtest once, on its own; it needs the results calendar (the events job).

## P. Idea-first research (a rule from 2026-10-28)

The review is right that Jeron's research has been mostly parameter search: 60 variants
on the same ten years. Done properly (review-v1, item 7) the deflated Sharpe of
rs-pullback-v1 is 0.37 counting the 60 as independent and 0.83 counting them as the 3.6
independent trials their correlation says they are worth, short of the 0.95 bar either
way. Every new trial makes it harder to believe any of them. From now on:

1. A new strategy family starts from a published, documented anomaly, cited in its plan.
2. The plan (rules, data, how it is judged) is committed before the code that runs it,
   and the run happens once.
3. One grid point unless the source gives a range; at most two axes of two values.
4. A result that looks better is a new pre-registered version that is paper-traded
   first, never a change to the version already trading.
5. Every report gives the deflated Sharpe against all variants tried so far.

Already in Jeron and idea-first: `results-drift-v1` (post-earnings drift),
`momentum-v1` (12-1 momentum), `quality-trend-v1` (quality in an uptrend, a form of
quality-momentum). Now `reversal-v1` (short-term reversal). The review's three named
anomalies are therefore all covered: PEAD by results-drift, quality-momentum by
quality-trend, short-term reversal by reversal.

## What this plan doesn't claim

- No new edge is shown here. reversal-v1 has not been run on data; R4 has not been run.
- The review's "2023 alone carrying the average" was not re-checked here; the per-year
  table on Research > Backtests for rs-pullback-v1 is where to look.
- A drawdown rule can't stop a determined owner: a 20-word note is friction and a
  record, not a lock. The 15% pause remains the hard stop.
