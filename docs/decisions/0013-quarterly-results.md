# 0013: Fundamentals from NSE's quarterly XBRL filings

Date: 2026-10-11. Status: proposed.

**Question.** Where do point-in-time fundamentals come from (M6 part 2, spec sections 2
and 3)?

**Source.** NSE's Corporate Filings > Financial Results page lists every results filing:
company, standalone or consolidated, the quarter, the link to its XBRL file and when NSE
published it. The page turns scripts away, so its CSV is saved by hand, one file per
quarter. The XBRL files themselves are on NSE's archive, which Jeron downloads (about one
a second). The first file Abhishek saved (quarter ended 31 Dec 2024) lists 3,816 filings
by 2,109 companies; 96% of the names match a stock in NSE's equity list, and the
filings' own symbol covers renamed companies. Reliance, TCS, HDFC Bank, SBI and ten
others match their published results.

**Decision.**
1. `financial_results` stores one row per filing: the quarter's revenue, other income,
   finance costs, depreciation, profit before tax, tax, profit (total and to the
   parent's owners), EPS, paid-up capital and face value, plus every numeric fact of
   the quarter (JSONB). Rows are added, never changed; a revised filing is a new row.
   A filing is known from `disseminated_at`.
2. `fundamentals-import FILE...` loads the CSVs: liquid stocks only (₹5 crore median
   daily turnover in some year) unless `--all`, consolidated when the company files
   one, else standalone. XBRL files are kept in the data folder, so a stopped run
   carries on.
3. The fundamental score `fund-v1` (`app/fundamentals/score.py`): quality 70 points
   (12-month sales and EPS growth, 3-year sales growth, profitable quarters of the last
   eight, net margin against a year ago, interest cover) and valuation 30 points (P/E
   against the stock's own P/E at its last 20 filings). P/E uses the share count of the
   newest filing, so splits don't distort it. Fewer than four consecutive quarters, or
   a newest quarter more than 200 days old, is no score. These points are a starting
   point for the backtester, not a finding.

**Not covered yet, and said so on the stock page.** ROE, ROCE, debt, operating cash flow
and promoter pledges need the half-yearly balance sheet and shareholding filings. Of the
spec's hard rejects only a qualified audit opinion is checked.

**History.** NSE's filing list goes back to 2016, but XBRL starts with some filings in
2018 and nearly all from 2019, so scores are possible from about 2019. Older forms (banks
and small companies before about 2021) leave out the quarter's dates; the quarter then
comes from the list. The lists saved in October 2026 have almost nothing after the
December 2024 quarter.

**Next.** With every quarter loaded: the combined three-brain strategy versions
and the M6 report (docs/plans/M6.md, scope item 5).
