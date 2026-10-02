# Jeron: notes for coding agents

Read `docs/spec.md` first. It is the brief, including how to work (section 0):
plan each milestone in `docs/plans/M<n>.md`, one branch and PR per milestone, tests
are part of done, never commit secrets.

## Layout

- `backend/` Python 3.12, FastAPI, SQLAlchemy 2, Alembic, managed with `uv`.
  - `app/models.py` schema. Prices are stored raw per source; adjusted series are
    derived. Point-in-time tables (index membership, delisting dates) are never
    overwritten.
  - `app/data/provider.py` the `DataProvider` protocol every data source implements.
  - `app/data/` market data: `nse.py` (bhavcopy + PR bundle), `nse_lists.py` (index
    closes, security list, Nifty 500 list, symbol changes), `yahoo.py` (second
    source), `adjust.py` (corporate-action factors), `crosscheck.py`, `quality.py`,
    `store.py` (database access), `pipeline.py` (jobs). Pure modules have no database
    imports; domain enums live in `app/enums.py` for that reason.
  - `app/indicators.py` indicators (pure functions, checked against TA-Lib in
    `tests/test_indicators_reference.py`; TA-Lib is a dev dependency only).
  - `app/scan/` the daily scan: `universe.py` (rules), `score.py` (technical score,
    versioned as `SCORE_VERSION`), `job.py` (database job). Changing points or rules
    means a new score version.
  - `app/cli.py` jobs: `backfill`, `lists`, `crosscheck`, `quality`, `scan`,
    `asm-import`, `daily`, `holidays`.
  - `app/calendar/` NSE trading calendar; holidays live in `nse_holidays.csv`.
  - `alembic/versions/` migrations. Generate with autogenerate, then review.
- `web/` Next.js 16 (App Router, TypeScript, Tailwind 4). Server components call the
  backend at `JERON_API_URL`.

## Commands

Backend (from `backend/`):
- `uv sync` install
- `uv run pytest -q` tests; database tests run when `JERON_TEST_DATABASE_URL` is set
  (e.g. `postgresql+psycopg://jeron:jeron@localhost:5432/jeron_test`)
- `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
- `uv run alembic revision --autogenerate -m "..."`, `uv run alembic upgrade head`
- `uv run uvicorn app.main:app --reload` (needs `JERON_DATABASE_URL`)

Web (from `web/`):
- `npm ci`, `npm run dev`, `npm run lint`, `npm run typecheck`, `npm run build`

Everything: `docker compose up --build` from the repo root.

## Conventions

- Money and prices are `Decimal` / `Numeric`, never float, in stored data.
- Times are IST for market logic; store timestamps with time zone.
- Raw prices are never changed. Adjusted prices are computed on read from NSE
  corporate actions (`source = "nse"`); see `docs/decisions/0003`.
- Indicators run on split/bonus-adjusted prices; the scan refuses to run (and stores a
  blocked run saying why) when the day's quality report FAILs or inputs are missing.
- NSE's archive answers bursts with 403 "Access Denied"; keep requests at about one
  per second and retry (the `Fetcher` does this).
- Settings come from env vars prefixed `JERON_` (`app/config.py`).
- CI (`.github/workflows/ci.yml`) runs backend checks, web checks, and a Docker Compose
  smoke test. Keep it green.
