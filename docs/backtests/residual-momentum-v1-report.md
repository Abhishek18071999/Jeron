# residual-momentum-v1 on NSE data: the deciding run, 2026-11-11

The plan (`docs/plans/residual-momentum-v1.md`, pre-registered 2026-11-07) said: run once
on NSE data, no rule changes, read the holdout once. This is that run.

**Verdict: it passes all seven section 6 checks, so by its plan it is live-eligible for
paper trading. It is not better than what Jeron already has.** Its evidence rating is
*weak*, the plan's own prediction (a higher Sharpe and a smaller drawdown than
`momentum-v1`) did not show, and its holdout year made no money. `fip-momentum-v1` is
still the strongest version; `momentum-v1` had the best holdout.

## The numbers

Walk-forward test years from late 2019, after costs, `engine-v3`, holdout from 2025-11-10
to 2026-11-09. The other three were re-run on the same database the same day.

| | Trades | Expectancy | Profit factor | CAGR | Max drawdown | Sharpe | Regimes positive | Holdout | Holdout return | Checks | Evidence | Deflated Sharpe, own grid | against all 70 variants |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **residual-momentum-v1** | 203 | 0.458R | 1.60 | 13.1% | 15.1% | 0.68 | all three | +0.170R (45), profit factor 0.74 | 0.0% | 7 of 7 | **weak** | 0.95 (0.9467) | 0.23 |
| fip-momentum-v1 | 202 | 0.416R | 1.79 | 13.9% | 13.5% | 0.71 | all three | +0.549R (43), 2.48 | +11.5% | 7 of 7 | strong | 0.95 | 0.26 |
| momentum-v1 | 209 | 0.685R | 1.79 | 13.0% | 15.0% | 0.64 | all three | +0.594R (40), 2.36 | +24.0% | 7 of 7 | moderate | 0.89 | 0.21 |
| rs-pullback-v1 | 279 | 0.358R | 1.65 | 17.2% | 13.4% | 0.96 | bull, sideways | -0.012R (54), 0.93 | +0.5% | 6 of 7 | weak | 0.97 | 0.47 |

Nifty 500 buy and hold: Sharpe 0.58 and a 38.3% drawdown over the test years, +0.2% in the
holdout year.

By year, `residual-momentum-v1`: 2019 +0.35R (6 trades), 2020 +0.45R (37), 2021 +1.53R
(26), 2022 +0.34R (27), 2023 +1.27R (26), 2024 -0.33R (36), 2025 +0.09R (45).

## Reading it

- **The gates pass, narrowly where it matters.** The Sharpe check is 0.68 against the
  index's 0.58. The holdout check passes on the average R (+0.17R) while the holdout's
  profit factor is 0.74 and the account ended the year flat: the average is carried by a
  few small-rupee winners, and in money the year lost a little before interest. The
  evidence layer fails it for exactly that.
- **The rating is weak** (2 of 11 checks failed): the holdout's profit factor is under 1,
  and the deflated Sharpe on its own grid is 0.9467 against the 0.95 needed. It survives
  doubled slippage, higher charges, late entries, and the loss of its five best trades or
  its best year (2021).
- **The plan's prediction did not hold.** It predicted a lower drawdown and a higher
  Sharpe than `momentum-v1` at a similar expectancy. The drawdown is the same (15.1%
  against 15.0%), the Sharpe is a little higher (0.68 against 0.64, far inside the noise),
  and the expectancy is a third lower (0.46R against 0.69R). Its daily returns correlate
  0.72 with `momentum-v1` and 0.73 with `fip-momentum-v1`: lower than on Yahoo data (0.85)
  but it is the same family, falling in the same year (2024).
- **The Yahoo result did not carry over.** On Yahoo's 346 surviving stocks it had the best
  Sharpe of any version (1.27, CAGR 21.4%, `yahoo-2026-11-10/`). On the full NSE universe
  with delisted stocks, that became 0.68 and 13.1%. Most of the Yahoo figure was
  survivorship.
- **Against every variant tried, nothing stands out.** With all 70 variants counted, the
  deflated Sharpe is 0.23 for this version, 0.26 for fip, 0.21 for momentum and 0.47 for
  rs-pullback. None is near 0.95: ten years of backtests cannot rule out luck for any of
  them. Only forward results can.

## About this database

The runs were made on a fresh load of NSE's archive (bhavcopies, index closes, lists,
board meetings; 2016-01-01 to 2026-11-09, 2,939 stocks, 2,689 sessions), not on the
install's own database. Differences from the 2026-11-06 report's database:

- three sessions later, so the holdout starts on 2025-11-10 instead of 2025-11-07;
- Nifty 500's close for 2016-06-20, 2023-04-10 and 2023-04-11 could not be downloaded;
- no second-source cross-check, no quarterly results, no ASM import and no news labels
  (none of the four strategies uses them);
- every quality report is WARN (no cross-check), none FAIL.

The comparison strategies moved with it: `fip-momentum-v1` 0.416R and Sharpe 0.71 here
against 0.493R and 0.85 on 2026-11-06, `momentum-v1` 0.685R against 0.667R, and
`rs-pullback-v1`'s holdout from +0.003R to -0.012R, which flips its seventh check. That
check sat on zero before and still does; treat it as unchanged, not as a new failure. The
size of these moves is itself a caution about reading small differences between versions.
The install's own run (`python -m app.cli backtest --strategy residual-momentum`) is the
one of record, and should be close to this.

## What follows

1. `residual-momentum-v1` may paper-trade with alerts in the long-term section, as its
   plan says. Real money needs the paper gate (3 months, 30 trades) and a moderate or
   strong rating; it has neither. Its status is the owner's to set.
2. It does not replace anything. `fip-momentum-v1` keeps the best evidence and
   `momentum-v1` the best holdout. A third account from the same family adds little:
   the three correlate 0.72 to 0.73.
3. No `residual-momentum-v2`. The idea was tested cleanly and came out as momentum with a
   lower expectancy. A changed version would only add trials.
4. The ranking of the momentum versions changes with the database and the week. The
   honest reading from 2026-11-06 stands: the family is real enough to paper-trade, the
   order inside it is not known, and the paper accounts are what will tell.

## Files

`nse-2026-11-11/`: `runs.json` (the four stored runs without equity), `equity.json`
(daily equity, cash-sweep line and Nifty 500 per run), `gates.txt` (every gate and
evidence check), `deflated-all.txt`, `scripts/export.py`. Gates and deflated Sharpe were
printed with `runs-2026-11-06/scripts/extract.py` and `dsr_all.py`.
