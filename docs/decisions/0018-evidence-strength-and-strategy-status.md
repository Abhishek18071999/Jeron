# 0018: Evidence strength beside the gates, and a status for every strategy

Date: 2026-10-26. Status: built (docs/plans/confidence-v1.md).

**Question.** rs-pullback-v1 passed all seven section 6 gates with a holdout expectancy of
+0.022R, a holdout profit factor of 0.96 and a deflated Sharpe of 0.39 against 52
versions tried. The gates said "live-eligible"; the evidence says "not shown". How should
Jeron say how trustworthy a pass is, and make sure a pass never reads as "ready for real
money"?

**Decision.**
1. Keep the seven gates exactly as they are; they still decide research only vs paper.
   Add a separate evidence-strength rating (`app/backtest/confidence.py`) from bootstrap
   intervals, the holdout, the deflated Sharpe, cost and timing re-runs, the parameter
   grid and concentration. Its thresholds are fixed in code before any rating was seen,
   and versioned (`CONFIDENCE_VERSION`).
2. Every strategy version has a status: Research, Paper, Small capital, Approved or
   Retired, with the date, the reason and who set it (`strategy_status_changes`,
   append-only). Jeron derives Research, Paper and Retired. Only I set Small capital or
   Approved, and Jeron refuses unless the paper gate passed and the evidence is moderate
   or strong (Small capital), or the real gate passed after Small capital (Approved).
3. A retired version resumes paper trading only after a backtest run made after the
   retirement passes the gates and I record the revalidation with a reason. A few
   winning trades don't revive it, and `paper --restart` no longer reopens it on its own.
4. The paper record is read against the backtest's distribution for that many trades
   (`app/analytics/health.py`) and called ordinary variance or deterioration, so a
   normal losing stretch isn't read as a broken edge. The spec's 50-trade retirement
   rule is unchanged; Jeron reports how often it would retire a strategy as good as its
   backtest, for me to decide whether to change it.
5. Status and evidence are labels. They change no fill, size, gate or signal.

**Why not fold the rating into the gates?** Changing the gates would re-judge every
stored run after the fact and change which strategies paper-trade. A separate layer
keeps every earlier result comparable and adds the missing question, "how sure?".

**Why fixed thresholds instead of a score?** A score invites tuning until a favourite
strategy rates well. Pass/fail checks with the value beside each say exactly what is
missing.
