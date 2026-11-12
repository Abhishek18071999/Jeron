# fundamentals-fetch-v1: quarterly results after December 2024

Status: built 2026-11-11. Asked for by Abhishek's standing request (the most profitable
realistic strategy): `quality-trend-v1`, the only fundamentals strategy, could not trade
after early 2025 because the results stopped.

## The problem
NSE's "Financial Results" list, which `fundamentals-import` reads as a saved CSV, ends
with the December 2024 quarter. From the March 2025 quarter companies file under
"Integrated Filing - Financials". Saving the old CSV again never brings a later quarter,
so every fund-v1 score went stale 200 days after December 2024 and `quality-trend-v1`
sat in cash.

## What is built
- `app/data/fundamentals.py` (pure): `read_integrated_list` turns one page of the list's
  JSON into the same `FilingRef`s the CSV gives; `integrated_standard` maps the XBRL form
  to the CSV's "IND AS" values, because `quarter_of` scores interest cover only for
  "Ind-AS New" filers; `integrated_quarter_ends`.
- `app/fundamentals/job.py`: `fetch_integrated` pages through the list for each quarter
  end with the project's `Fetcher`; the rows then go through `import_results` unchanged
  (liquid stocks only, consolidated preferred, every revision kept, stored once).
- `python -m app.cli fundamentals-fetch [--start DATE] [--all]`. With no `--start` it
  lists from the newest stored quarter, so late filers and revisions are picked up.
- Point in time: a filing is dated by the later of its broadcast and creation times; a
  revision has only a creation time and is known from then.
- `parse_xbrl` needed no change: the integrated XBRL uses the same contexts.

## Not built
- It is not scheduled. Run it by hand in results season (mid-month after each quarter
  end, and again a fortnight later). Adding it to `weekly` is a small follow-up once it
  has run cleanly on the install a few times.
- Half-yearly balance sheets and cash flow for fundamentals-v2 come with the same files
  (`OneI`, `FourD`) and are stored; `health.py` is untouched and unverified on them.
- No new score version: fund-v1 is unchanged, it only has data again.

## Tests
`tests/test_fundamentals.py`: the list reader on a fixture cut from the real list
(original, revision, NBFC and bank forms), refusal of other JSON, the quarter ends,
paging, and an integrated XBRL parsed like the old form.

## First use
The research run in `docs/backtests/quality-trend-v1-holdout-report.md`. A first load
with every filing labelled as a non-"Ind-AS New" form scored ordinary companies as
lenders; that is what `integrated_standard` and its test are for.
