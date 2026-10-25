# Explain a stock, compare, account equity (explain-v1)

Built 2026-10-25 on `claude/project-thread-2ydnzm`, after the platform audit
(`platform-audit-v1.md`). Decision 0016.

## What it does

- `GET /stocks/{symbol}/explain`: the brief, built without an LLM, and the newest stored
  wording of it. Facts come from what Jeron already stores: the latest completed scan
  (score, rank, EMAs, RSI, ADX, volume ratio, 52-week high, ATR %, relative strength,
  support and resistance), the market mood, results and ex-dates ahead, fund-v1 and its
  facts, announcements of the last 90 days with the news labeller's labels, the newest
  signal (levels adjusted to today's basis, backtest record) and the journal's holding.
- `POST /stocks/{symbol}/explain/narrate` `{question?}`: the LLM's wording, checked
  (`check()` in `app/explain/narrate.py`) and stored in `explanations` whatever the
  outcome. 409 without a key, at the monthly cap or at 50 a day.
- `GET /stocks/compare?symbols=A,B,C`: up to three briefs.
- `GET /portfolio/equity`: the account's equity each session from the first buy, its
  peak, worst drawdown, return, and the same capital in the Nifty 500.
- Web: the "Explain this stock" card on every stock page (with the optional wording and
  question box, through a server action), `/stocks/compare`, and the account equity
  chart on Portfolio. The Guardrails card's peak is the curve's.

## The checks on the LLM's reply

1. JSON in the expected shape, 1 to 10 points, each citing at least one fact id.
2. Every cited id exists.
3. Every number in a point appears in the label, value or date of a fact it cites
   (normalised: `₹1,234.50` = `1234.5`). Rounding counts as a new number.
4. No advice, forecast, probability or certainty phrases (`BANNED`).

Any failure: status `rejected`, no points shown, the problems listed. A provider error:
status `failed`.

## Tests

- `tests/test_explain.py` (16): setup states, brief sections and unknowns, the number and
  phrase checks, the question as data, the Claude and chat writers with fakes.
- `tests/test_explain_db.py` (4): the API on a real Postgres with a fake writer: stored,
  reused, refused, capped, failed; compare; a signalled stock's setup.
- `tests/test_portfolio_equity.py` (3): the curve by hand, the peak in the account state.
- `tests/test_market_db.py`: `/portfolio/equity` against the seeded journal.
- `web/src/lib/auth.test.ts` (5, `npm test`): the login's scrypt hash and TOTP codes
  made by the backend, RFC 6238 vectors, replay, lockout, session signing and expiry.

## Not done

- No intraday data: the brief is end-of-day and says so.
- Capital changes (deposits, withdrawals) are not known, so the equity curve assumes a
  fixed `JERON_CAPITAL`.
- The real LLM providers were not called here (no key in the build container); the
  writers are tested with fakes of each provider's reply shape.
