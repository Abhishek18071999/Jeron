# 0003: Corporate actions from NSE's PR bundle; Yahoo as the second source

Date: 2026-09-30. Status: accepted.

**Decision.**
1. Corporate actions come from the `bc` file in NSE's daily PR bundle, parsed from its
   purpose text. Splits and bonuses are applied with exact factors. Dividends are
   applied only for a total-return view. Rights issues, demergers and schemes are
   logged but not applied.
2. The second source is Yahoo Finance's chart API, called directly (no `yfinance`
   package). Its prices are converted back to raw with its own split events and
   compared close by close with NSE.
3. Adjusted prices are computed when read, never stored.

**Why.**
- The bhavcopy's previous-close column is not adjusted on ex-dates in either format,
  so it cannot reveal corporate actions. NSE's corporate-actions API sits on
  `www.nseindia.com` behind cookie checks; the PR bundle is a plain archive file.
- Broker charts show split- and bonus-adjusted prices without dividend adjustment,
  so that is the default to make spot checks line up.
- Rights and demerger factors need the issue price or the demerged value, which the
  files don't carry; guessing would silently corrupt history. Flagging is safer.
- Yahoo is free, covers NSE symbols, and is independent of NSE's files. Calling the
  JSON endpoint directly avoids a scraping library that changes often.

**Consequences.** Missing a PR file for a day could miss an action; the >20% move
check and the Yahoo split comparison catch splits and bonuses that slip through.
When Kite Connect is added (M4–M5) it can replace or join Yahoo as a source through
the same comparison.

**Amendment (2026-10-03): Yahoo's scaling for later actions.** Yahoo scales its whole
history for corporate actions its split events don't list (some bonuses, demergers,
rights issues, ETF unit changes; for example BAJFINANCE's 2025 4:1 bonus), so
un-scaling with its split events leaves old closes off from NSE's by a constant factor.
On the full 2016-2026 history that made 1,498 of 2,664 days FAIL quality. Now a close
that differs from NSE's by the same factor as the stock's median Yahoo/NSE ratio on the
10 sessions before or after it (at least 3 sessions on that side) counts as scaled, not
as a mismatch; it is listed in the report with the factor. A wrong close stands out
from its neighbours and is still a mismatch. A stock whose Yahoo prices are wrong for
weeks on end would also look scaled; NSE stays the source of truth, so this only
weakens the second-source check for such a stock, it never changes a price.
