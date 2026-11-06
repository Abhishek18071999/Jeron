# Fundamentals v2: balance sheet, cash flow and valuation on the stock page

Status: built 2026-11-01, asked for by Abhishek ("do what is left" of spec section 2's
fundamentals list).

## What was missing
Spec section 2 asks for ROE, ROCE, debt/equity, interest cover, operating cash flow vs
profit, promoter holding and pledge, and valuation (P/E, EV/EBITDA) vs the stock's own
history and its sector. fund-v1 had growth, margins, interest cover and P/E against the
stock's own five years.

## Where the data is
The results XBRL filings Jeron already downloads carry more than the quarter's profit and
loss: the half-yearly and annual ones (September and March quarters) also have the
balance sheet on the last day (context `OneI`) and the year-to-date cash-flow statement
(context `FourD`, sometimes `OneD`). The parser kept only `OneD`. Of 25,378 cached
filings, about 5,000 have a balance sheet and 8,750 an operating cash flow. No new data
source.

## What is built
- `parse_xbrl` also returns the balance-sheet and year-to-date facts; two new JSONB
  columns on `financial_results`, `balance` and `ytd`; the importer stores them.
- `fundamentals-reparse`: fills them for filings already stored, from the cached XBRL
  files (no download; a filing whose file isn't cached is skipped and counted).
- `app/fundamentals/health.py` (pure), from the quarters known on a day:
  - **ROE**: trailing-four-quarter profit to owners over the owners' equity of the latest
    balance sheet;
  - **ROCE**: trailing profit before tax plus finance costs over equity plus borrowings;
  - **Debt/equity**: current plus non-current borrowings over equity;
  - **Operating cash flow vs profit**: each of the last three financial years (March
    filings), and a warning when it was negative in all three (spec section 3's hard
    reject, shown here as a warning);
  - **EV/EBITDA**: market value plus borrowings minus cash, over trailing profit before
    tax plus finance costs plus depreciation;
  - **Balance sheet as of**: the date of the balance sheet used; older than 400 days is
    treated as unknown.
  Banks and NBFCs (non Ind-AS forms) get ROE only: borrowings are their raw material, so
  ROCE, debt/equity and EV/EBITDA aren't meaningful and are left out with a note.
- The stock page's Fundamentals card shows them, with what each means.

## What is not changed
- **fund-v1 is unchanged.** The new measures are shown, not scored: changing the points
  means a new score version and a re-test of `quality-trend-v1`. A fund-v2 that scores
  them needs its own plan and backtest.
- **Promoter holding and pledge** come from the shareholding-pattern filings, a separate
  download Jeron doesn't have yet; and **valuation against the sector** needs point-in-
  time sectors. Both are said on the card, not guessed.

## Tests
Parser contexts (quarter, balance sheet, year to date), each measure on hand-built
quarters, the bank case, the stale balance sheet, the three-year cash-flow warning, the
API shape and the migration.
