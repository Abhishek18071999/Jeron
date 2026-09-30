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
