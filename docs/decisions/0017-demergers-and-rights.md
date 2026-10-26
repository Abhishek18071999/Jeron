# 0017: Demergers and rights issues are adjusted

Date: 2026-10-26. Status: accepted. Amends 0003 (point 1).

**Decision.**
1. A rights issue is adjusted with the theoretical ex-rights price: `n` new shares for
   every `h` held at issue price `S`, previous close `P`, factor
   `(h x P + n x S) / ((h + n) x P)`. The ratio is in NSE's purpose text ("RGHTS
   119:758"), and so is the price, as a premium ("PRM RS 218", "@ PREMIUM RS 1,201") or
   an issue price ("@ RS 50"). The premium is used as the price; the face value (₹1-10)
   is left out. A rights issue priced at or above the previous close is not adjusted
   (nobody takes it up, and NSE doesn't adjust it either), nor is one without a ratio
   or a price.
2. A demerger is adjusted with the price NSE's special pre-open session found on the
   ex-date: factor = ex-date open / previous close. Gaps under 2% are left alone, and
   so is a factor under 0.1 (bad data, not a demerger).
3. Capital reductions and schemes of arrangement stay logged and unadjusted. Quality
   check #9 keeps holding a stock that falls over 15% on one.

**Why.** Large Indian groups split businesses off often, and a demerger can open the
parent 30-50% lower. Unadjusted, that fake fall breaks every indicator Jeron uses: the
6-month relative strength rank behind `rs-pullback-v1` (the only live-eligible
strategy) drops the stock out of the leaders for six months, ATR jumps, the 52-week high
is unreachable, and an open position's stop is "hit". Decision 0003 chose flagging over
guessing because the value of the demerged business isn't in the files. The ex-date's
special pre-open price is not a guess: it is the market's price for the parent without
the demerged part, and it is what NSE's indices and most data vendors use. Rights
issues have a textbook factor once the price is parsed.

**Consequences.**
- The factor on a demerger's ex-date also removes whatever else moved the stock
  overnight. That is a small error on one day against a large one for months.
- Adjusted series, scans and backtests change for stocks with these events. Raw prices
  are untouched (0002), and adjusted prices are still computed on read, so nothing
  stored is rewritten. Backtest runs made before keep their numbers; new runs carry a
  new data fingerprint.
- Fewer stocks are held by check #9, so fewer signals wait for a check by hand.
- The spot check's adjustment log shows the factor used for each.
