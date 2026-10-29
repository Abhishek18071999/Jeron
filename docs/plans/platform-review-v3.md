# Platform review v3 (2026-10-28)

A third pass over `main` at `282275a` (PR #42 merged) after the owner asked for a
professional-grade platform: bugs, data accuracy, risk analysis, charts, speed. The
earlier passes are `platform-audit-v1.md` (API token, guardrails, data-outage alert,
explain a stock) and `post-review-v2.md` (paper first in a drawdown, reversal-v1); their
items are not repeated here. The spec stays binding: no automatic orders, the LLM only
labels news and re-words facts, no strategy changes after results are seen.

## What ran

- Backend before any change: **693 passed** with a local PostgreSQL 16; ruff and mypy
  clean. After: **710 passed**.
- Web: `npm test` (25, 2 new), `lint`, `typecheck`, `build` pass.
- The Portfolio, stock and journal pages were opened in Chromium (Playwright) against a
  local backend with **made-up random-walk prices** (desktop light, phone dark): no
  console errors, no sideways scroll. Screenshots are in the project files under
  `jeron/platform-v3/`, named `-test-data`. Nothing here was run on real NSE data.

## Gaps found, ranked

Ranked by what could cost real money or mislead a decision, then by effort.

| # | Gap | Kind | State |
|---|---|---|---|
| 1 | A split or bonus on a stock I hold broke the real position: the journal kept the old share count, so the position showed a fake loss (a 2:1 split read as -5R), the broker's GTT stop was sized for half the shares, a sale of the new share count was refused ("sold 200 but bought only 100"), the tradebook import couldn't match it, heat and sector exposure halved, and the equity curve (whose peak drives the drawdown brake) dropped on the ex-date. | Bug, data accuracy, risk | **Fixed** |
| 2 | Portfolio risk stopped at "if every stop is hit". No beta, no market-shock view, no tail loss, no warning that a gap opens below a stop, no measure of how closely the positions move together. | Risk analysis | **Built** |
| 3 | The stock chart had no volume, a fixed 2-year window, no comparison with the market, and no record of when signals came or when I bought and sold. It also kept the light palette when the phone switched to dark. | Charts, UX | **Built** |
| 4 | An exit plan used price adjustments whose ex-date is after the last close (an announced split moved today's stop before it happened). | Bug | **Fixed** with 1 |
| 5 | Every database test ran all 20 migrations down and up. | Speed (CI) | **Changed**: migrate once, then empty the tables; the suite went from 7m04s to 6m21s here, most of the time is the tests' own data loading |
| 6 | The NSE holiday file has 2025 and 2026 only; 2027 is not published yet (NSE issues it in December). The Setup page and the pre-open check already warn from November. | Data | Owner action in December: add 2027 from NSE's circular |
| 7 | A demerger's new shares and a subscribed rights issue are not journal positions: the exit plan adjusts the old stock's prices, but the new company's shares are not tracked. | Data accuracy | Not built: needs the allotment from the broker; enter it as a manual fill |
| 8 | The Portfolio page builds the pre-open check twice (positions and risk). | Speed | Not built: not measured on real data; worth sharing one build if the page gets slow |
| 9 | A web session lasts 30 days and can't be revoked on its own; changing the password or TOTP secret logs out every device (`web/src/lib/auth.ts`). | Security | Not built: one user, and the secret change already works as a revoke |

## 1. Held through a split or bonus

`app/journal/basis.py` (pure) restates fills to one share basis: a fill before an
ex-date has its shares multiplied by the action's ratio and its price divided so its cost
is unchanged. Rupee amounts (cost, proceeds, charges, gains, tax) never move. A 1:2 bonus
on an odd lot rounds down, as the broker pays the fraction in cash. Only splits and
bonuses are restated: they are the actions that change the share count. Rights issues and
demergers keep their price-only adjustment in the exit plan.

Every consumer goes through it: `entry_views` (journal, stock page, pre-open check,
portfolio), `add_fill` and `delete_fill` (a post-split sale is accepted), the tradebook
importer, the tax lots (`sales_this_year`, `journal_history`) and the equity curve (closes
on the same basis, so no fake drop). The journal's own stop now carries `stop_set_on`
(migration `17bc3b6809d8`), so a stop moved after the split isn't halved again; older
entries read as set on the first buy, which is what the exit plan assumed before. The
journal page says what was restated. Tests: `tests/test_journal_splits.py` (6 by hand, 3
on Postgres: journal, exit plan, broker stop, portfolio, equity curve, a sale after the
split).

## 2. Bad days (Portfolio)

`app/portfolio/risk.py` (pure), served at `/portfolio/risk`, shown as the "Bad days" card:

- beta of each stock and of the book to the Nifty 500 (250 sessions);
- the Nifty 500 down 5%, 10%, 20% in a day, each stock moving by its beta, before stops;
- one-day 95% and 99% VaR and the 97.5% expected shortfall by historical simulation:
  today's shares through each of the last 500 sessions' actual returns, all stocks on
  the same day, so their co-movement is the market's, not a model's;
- each stock's worst opening gap in those sessions and what it would cost past the stop;
- the average pairwise correlation (120 sessions) and pairs above 0.7.

Every input is a stored NSE price, split/bonus-adjusted. The card and the API say it is
history, not a forecast, and how many sessions each figure stands on; a stock with short
history or no stop is named in a note. Tests: `tests/test_portfolio_risk.py` (6 by hand,
2 on Postgres, one checking a split is not read as a gap).

## 3. Stock chart

Range buttons (3M, 6M, 1Y, 2Y, All; 1,000 sessions loaded), volume under the candles, a
second pane with the stock against the Nifty 500 rebased to 100 where the range starts,
an arrow on each signal's day (grey for research only) and a dot on each of my fills, and
the palette follows the system's light/dark setting while the page is open. Targets of a
held position now come from the signal's adjusted chart levels, so they sit on the same
basis as the candles after a split. `/stocks/{symbol}` candles carry the day's Nifty 500
close. Tests: `web/src/lib/chart.test.ts`, `test_stock_candles_carry_the_index`.

## What this doesn't claim

- No new edge and no change to any strategy. The risk card measures the owner's real
  positions; it does not size or pick trades.
- VaR and gaps come from at most two years of history. A crash that isn't in those
  sessions isn't in the numbers; the market-shock rows assume betas hold, and in a crash
  they rise.
- The new screens were seen with made-up prices only.
