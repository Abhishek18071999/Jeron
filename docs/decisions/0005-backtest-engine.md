# 0005: Own event-driven backtester, walk-forward with a holdout

Date: 2026-10-02. Status: proposed (M3).

**Decision.**
1. The backtester is our own small engine (`app/backtest/`) over numpy arrays, not a
   library such as backtrader or vectorbt.
2. It reuses the scan's universe rules and score code, so a backtest trades the stocks
   the scan would have shown on each day, with data up to that day only.
3. Every strategy is evaluated by walk-forward (expanding training window, yearly test
   windows) and a final 12-month holdout, in one continuous simulation. Each strategy
   has a small grid (at most 12 points); every point tried is logged and the result is
   corrected for the number of trials (deflated Sharpe ratio).
4. Runs are stored and never overwritten, with a fingerprint of the input data.

**Why.**
- The spec's rules (entry zones, circuit locks, partial exits, Indian costs, portfolio
  heat, drawdown brakes) are specific; libraries would need as much code to bend as to
  write, and would hide what happens on each day.
- Sharing the scan's code means a backtested edge is an edge of what Jeron shows.
- Few parameters, logged trials and a holdout are the spec's overfitting guards; a
  continuous simulation keeps portfolio effects (slots, heat, drawdown) realistic.
- Stored runs make repeated peeks at the holdout visible.

**Consequences.** Simulations are fast (seconds per strategy on ten years) because
signals are precomputed per grid point. Changing a strategy's rules means a new
strategy version. Sector and correlation limits are not simulated until M4.
