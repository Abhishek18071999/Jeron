# 0001: Stack and repository layout

Date: 2026-09-30. Status: accepted.

**Decision.** One repo with `backend/` (Python 3.12, FastAPI, SQLAlchemy 2, Alembic,
uv) and `web/` (Next.js 16, TypeScript, Tailwind), run together with Docker Compose
and PostgreSQL 16.

**Why.**
- Python has the best tooling for market data, indicators and backtesting (pandas,
  NumPy, TA-Lib). FastAPI gives a typed API with little code.
- Plain PostgreSQL is enough for one user and daily bars (~2,000 stocks × 250 days ×
  10 years ≈ 5M rows). TimescaleDB can be added later without changing the schema.
- Next.js 16 rather than 15: 15.x pulled in a PostCSS version with open security
  advisories; 16 has none.
- Docker Compose makes "run it on my laptop" one command on Windows or Mac.

**Consequences.** Two languages to maintain. Shared API types will be generated from
the backend's OpenAPI schema when the web app starts consuming real data (M5).
