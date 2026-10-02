# 0004: Rule-based universe, versioned technical score, own indicator code

Date: 2026-10-02. Status: proposed (M2).

**Decision.**
1. The universe is rebuilt each day from rules on the bhavcopy (EQ series, ₹20 price,
   ₹5 crore 20-day median turnover, 200 sessions of history) plus GSM (NSE's
   security list) and ASM (imported). Nifty 500 membership is a label, not a filter.
2. Indicators are our own small pure-Python functions, checked against TA-Lib in
   tests. TA-Lib is a dev dependency only.
3. The technical score is a sum of named components with fixed points, versioned
   (`tech-v1`). Every result stores each component's value and points.
4. The scan refuses to run when the day's quality report FAILs, or the Nifty 500 close
   or a recent security list is missing, and records a blocked run with the reasons.

**Why.**
- A rule-based universe needs only the bhavcopy, which we hold back to 2016, so it is
  point in time with no survivorship bias. NSE's archive has no Nifty 500 membership
  history, so using it as a filter would bias backtests.
- Our own functions keep the app free of a C library at run time (simpler Docker and
  Windows setup) and work on plain lists for both the scan and the backtester; the
  TA-Lib comparison proves they are right.
- Named points make a score explainable and give M3's backtester a few clear
  parameters to test, instead of a black box.
- Spec rule: if data is missing or stale, publish nothing rather than guess.

**Consequences.** Relative strength is scored as a percentile within the day's
universe, so a stock's score depends slightly on the others; the backtester sees the
same thing. Re-weighting after M3 creates `tech-v2`, and old runs keep their version.
