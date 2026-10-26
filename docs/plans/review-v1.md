# Review v1: the 2026-10 trading review

Date: 2026-10-26. A 15-point review of Jeron (Abhishek, from an outside trader's
reading of the project document). Each point was checked against the code first. This
file says what was built, what already existed, what was pushed back on, and which
points are research questions. The research options were fixed here before any run;
their results are in `docs/backtests/review-v1-report.md`.

Nothing here changes a strategy version, a paper account's rules or how a signal is
made. The project's own rule stands: no new strategy goes live until paper trading has
given a verdict on `rs-pullback-v1`.

## Built

| # | Point | What was built |
|---|---|---|
| 1 | Dead-man's switch | `app/alerts/watchdog.py`. At 19:45 IST on trading days (`JERON_SCHEDULE_WATCHDOG`) the scheduler checks the daily summary (or the "data has not arrived" alert) went out; if not, one alert, **JERON DID NOT FINISH TONIGHT'S RUN**, says whether a run is still going, the newest prices and the scan's state. A switch inside the laptop can't report the laptop being off, so the daily run also calls `JERON_HEARTBEAT_URL` (optional, off when empty) for an outside monitor; `docs/runbook.md` says how to set one up. |
| 2 | Morning entry re-check | The 08:30 pre-open check now has **BUYS AT THE OPEN**: each live signal valid today with no journal entry is planned on the real account as the Trade page plans it (heat, positions, drawdown brake, loss limits, sector, results blackout, kill switch), one after another so two buys together can't pass limits each passes alone; skipped if quality check #9 held it or it has a split, bonus, rights or demerger ex-date today (noted for a dividend). It ends with the order: a limit at the zone top, not below the stop. Pushback: Jeron has end-of-day data only, so at 08:30 it knows nothing about the open that it didn't know at 19:00. Gaps, circuits and late news are checked by the owner at 09:08 (the alert says how); a live check would need a broker feed (spec section 2, Kite, still the owner's decision). |
| 3 | Demerger and rights adjustment | Decision 0017. Rights by the theoretical ex-rights price, demergers by the ex-date's special pre-open price. |
| 5 | Holidays and restore | The 2026 list was already in `nse_holidays.csv` (four late-year dates still marked unverified there), with a warning from November when the next year is missing and a test that fails on 1 January. The weekly automatic restore test already existed (hardening-v1). Added: a quarterly manual restore drill on another computer, with a log table, in `docs/runbook.md`. 2027 can only be added once NSE publishes its circular (usually mid-December). |
| 10 | Missed entries | `app/backtest/missed.py`: every order skipped for opening above the entry zone is bought at that open anyway, with the same stop and exit rules, and compared with the trades taken on the same basis. Saved in every new backtest run's summary (`missed_entries`, reporting only) and in the research report. |
| 11 | Kill switch and runbook | `python -m app.cli stop-all --reason "..."` / `resume` (`app/halt.py`): no signal or watchlist alerts, new signals research only, no trade plan saved; exits keep coming (stopping them in a crisis would be the wrong reflex). `docs/runbook.md`: no summary, data wrong, alert wrong, alerts stopped, turmoil. |
| 12 | Tax note at the pre-open | The portfolio's tax timing notes (selling now vs after the 12-month mark, in rupees, with the year's ₹1.25 lakh exemption) now appear in the pre-open check as information only. Pushback: the 12-month mark matters for the invest tier; a positional trade (1-6 months) is short-term whatever it does, so "3 months in, hold 15 more days" doesn't arise. |
| 14 | A week without Jeron | `docs/runbook.md`: what comes back by itself, what is lost, what needs the owner. |

## Already there, so not built

| # | Point | Why not |
|---|---|---|
| 6 | Combined heat across correlated strategies | The real account's 6% heat cap already counts every open position, whatever strategy it came from (`app/plan/calc.py`, the plan's heat check uses the whole portfolio's open risk). Two momentum strategies live at once still share one 6%; at 1% a trade that is six positions, not 13. Only `rs-pullback-v1` is live-eligible; `trend-breakout-v1` failed section 6 and is research only. Paper accounts have their own 6% each by design (they are separate experiments). The morning re-check now also counts the day's earlier buys. |

## Research options (fixed before any run)

Run by `python -m app.cli research --trials --out report.md` on `rs-pullback-v1` with the
full walk-forward (grid picked on training data with the option on, out-of-sample after
costs, the latest 12 months as holdout). Not saved as backtest runs. Each option is a
`PortfolioRules` field or an entry filter that defaults off.

| # | Option | Rule |
|---|---|---|
| 4 | `results-sell` | Sell the whole position at the open of the results meeting's session (the first session on or after the meeting date). |
| 4 | `results-half` | Sell half there; the rest stays. |
| 8 | `crash-guard` | No new entries while Nifty 500 is up at least 8% over 20 sessions and was below its 200-day EMA at some point in the last 60 sessions (a violent rebound off a bear market: Daniel and Moskowitz, "Momentum crashes", 2016). One setting, no grid. |
| 9 | `no-time-stop` | The positional 60-session time stop doesn't sell. |
| 13 | `quality` | Enter only when fund-v1 is at least 50 where known. The review's cash-flow, pledge and dilution filters need data quarterly results don't carry; fund-v1 stands in. Needs fundamentals loaded. |

Also reported: item 7, the deflated Sharpe of `rs-pullback-v1` against the 60 variants
counted as independent and as the effective number of independent trials their daily
returns' correlation says they are worth (eigenvalue participation ratio); item 15,
the capital at which the 1%-of-volume cap starts cutting trades.

What a result can and can't do: these are five more trials on the same history. An
option that looks better is a candidate for a new strategy version, registered with its
rules before a run and paper-traded beside `rs-pullback-v1`. None is switched on here.

## Not built

- Intraday, F&O, shorts, auto-trading: out of scope (spec sections 1 and 12; the review
  agrees).
- A live pre-open price check: needs a broker data source the owner hasn't chosen.
