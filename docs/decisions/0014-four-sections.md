# 0014: Four sections by holding period, and the investing tier

Date: 2026-10-17. Status: proposed.

**Question.** Abhishek wants a separate section for swing, intraday, positional and
long-term investing, each running its own strategies and saying what to buy, when, how
much and why. How does that fit "no signal without a backtested strategy behind it"?

**Decision.**
1. A section is a view, not a new decision-maker: the strategies of one tier, their
   stage, and their paper accounts' signals (`app/sections/`, `/sections`, the web app's
   Trade pages, the Telegram summary). Each signal is shown as what (stock, setup,
   stop, targets), when (the session, the pre-open limit order, what cancels it), how
   much (shares, cost, rupees at risk, both as a share of capital) and why (its reasons,
   exit plan, event risk and the strategy's out-of-sample record).
2. A section without a strategy that passed spec section 6 says "nothing to buy" and
   shows research-only signals apart, marked as not trades. Today that is swing (the M3
   strategies failed) and, until its backtest runs, long-term.
3. **Long-term** gets the spec's investing tier (`Tier.INVEST`: 15 positions, T1 +3R,
   T2 +5R, 4 x ATR trail, 250-session time stop) and its first strategy,
   `quality-trend-v1`, pre-registered in `docs/plans/sections-v1.md` before any run. It
   is the first strategy that uses fund-v1, computed point in time from the results
   filings (`Market.fund_score`). A strategy may now carry its own exit rule; this one
   sells when new results take fund-v1 below 50.
4. **Intraday** is shown as not running. Jeron has only end-of-day data; NSE publishes
   no free intraday history and Yahoo keeps 1-minute bars for 7 days. A broker API
   (Zerodha Kite Connect's paid plan, or Angel One's free SmartAPI) would be the source;
   spec section 0 says to ask before adding a data vendor, so nothing is fetched.

**Why.** It gives each horizon its own place without lowering the bar: the backtester
still decides which signals count, and a section with nothing honest to offer says so.

**Consequences.** Swing and positional keep every rule, number and golden trade; the
engine takes T1, T2 and the trail from the tier, which only changes the invest tier.
The combined book's deflated Sharpe stays against the 61 trials its plan named.
