# Tax helpers, small-trade warning, holiday-calendar warning

Remaining-work items C1 (warning part), C2 and C3, 2026-10-25. No strategy, score or
engine rules change: these are read-only helpers for the owner's real trades.

## C1. Holiday calendar coverage

NSE publishes next year's holidays in December, so the 2027 rows can't be added yet.
- `TradingCalendar.coverage_warning(today)`: a warning when this year is missing, or
  from November when next year is missing.
- Shown as a "Holiday calendar" step on `/setup` and a CALENDAR line in the pre-open
  message.
- `test_shipped_file_covers_this_year` fails from 1 January of a year not in the file,
  so CI says so the first day it matters.

## C2. Tax helpers (Portfolio)

- `realised_sales`: a journal entry's sales matched first in, first out against its
  buys, each fill's charges in its cost or proceeds.
- `long_term_exemption`: this financial year's net long-term gains, after this year's
  short-term losses, against the ₹1.25 lakh exemption: used and left.
- `sell_now_or_later`: for a profitable position within 60 days of the 12-month mark,
  the tax of selling now (20% short-term) against after the mark (12.5% above the
  exemption left in the financial year the later sale falls in; a whole new exemption
  when the mark falls after 31 March). Shown in the existing tax note.
- Estimates only: surcharge, cess, other accounts and income are unknown to Jeron.

## C3. Small-trade charges warning

- `costs.fixed_charges`: the charges that don't shrink with size: the DP charge on each
  day with a sale (two: half at T1, the rest later) plus any brokerage minimum
  (`CostModel.brokerage_min`, 0 for Zerodha delivery, so backtests are unchanged).
- `costs.small_trade_warning(risk)`: warns when those exceed 0.1R. With Zerodha's
  ₹15.34 DP charge that is below about ₹307 at risk.
- Shown, not blocking: a "Charges worth the trade" warning on the trade plan, a note on
  the signal alert and on the Trade section's signal card.
