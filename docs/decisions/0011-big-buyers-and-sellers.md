# 0011: Big buyers and sellers on the stock page, as information, not a signal

Date: 2026-10-11. Status: proposed.

**Question (Abhishek).** Should Jeron list the top people and companies buying and
selling a stock, and would it help?

**What is public in India.**
- **Bulk deals**: a client trading more than 0.5% of a company's shares in a day.
  **Block deals**: a single trade of ₹10 crore or more in NSE's block window. Names,
  side, quantity and price, published the same evening.
- **Insider trades** (SEBI PIT): promoters, directors and employees disclose within 2
  trading days to the company, which tells NSE within 2 more.
- **Shareholding pattern**: FII, DII, mutual fund and promoter holdings, once a quarter,
  up to 3 weeks after the quarter ends. Not built here (see below).

**What the data showed.** NSE's bulk-deal file for 2026-10-09: 155 deals in 39 stocks,
none of them in the Nifty 500. 54 of the 75 client-and-stock pairs were firms (QE
Securities, HRTI, Jump Trading, Mathisys...) that bought and sold the same stock the same
day: market makers and high-frequency traders moving volume, not investors with a
view. The useful rows were the rest, e.g. Peak XV Partners selling 12.2 lakh AWFIS
shares (₹29.8 cr) to a trust. So bulk deals are mostly a small-cap story and mostly
noise unless same-day traders are separated out; block deals and insider buys on the
market are the informative part.

**Decision.**
1. Store bulk and block deals (`deals`) and insider trades (`insider_trades`); rows are
   added, never changed. `app/data/deals.py` parses NSE's files (pure).
2. The `daily` job downloads `bulk.csv` and `block.csv` from NSE's archive. The archive
   only holds the latest day, so a missed day is lost unless imported; the panel says
   how many trading days are covered. History and insider trades load with
   `deals-import FILE`, from the CSV (or JSON) saved from nseindia.com, which turns
   scripts away (as with `events-import` and `asm-import`).
3. `/stocks/{symbol}/deals` and a "Big buyers and sellers" card on the stock page: net
   buyers and net sellers over the last year by rupee value, same-day traders listed
   apart, every deal, insiders' trades with promoters' and others' net buying on the
   market (ESOPs, gifts, transfers and off-market deals are counted, not summed).
4. **Not a signal.** Nothing here changes a score, signal or strategy. Spec section 6
   requires a backtest before anything affects a trade, and there is no history to test
   on yet: the archive has no past files. Once a year or more of deals and insider trades
   is stored (imported or collected), "promoter buying on the market" and "a block sale
   by a large holder" can be pre-registered and tested like any other strategy.

**Not done.** Quarterly shareholding patterns (FII/DII/mutual fund trends): NSE serves
them per company and quarter from www.nseindia.com only, and they are weeks old when
published. A screener CSV export could fill it later, with Abhishek's approval
(spec section 0.6). Matching deals across symbol changes is not done: deals stay under
the symbol NSE published them with.
