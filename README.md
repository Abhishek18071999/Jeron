# Jeron

A personal research and decision-support tool for Indian equities (NSE/BSE): it
scans the market, backtests every rule honestly, proposes trades with a full risk
plan, and journals the results. Decision support, not investment advice.

The full brief is in [docs/spec.md](docs/spec.md).

## Run it on your computer

You need [Git](https://git-scm.com/downloads) and
[Docker Desktop](https://www.docker.com/products/docker-desktop/).

```sh
git clone https://github.com/Abhishek18071999/Jeron.git
cd Jeron
cp .env.example .env        # Windows: copy .env.example .env
docker compose up --build
```

Open http://localhost:3000. The page shows whether the backend and database are
running. Stop with Ctrl+C; your data is kept in a Docker volume.

## Load market data

With Jeron running, open a second terminal in the `Jeron` folder.

1. Download NSE's price history since 2016 (about 1.5 hours; if it stops, run it
   again and it continues where it left off):
   ```sh
   docker compose exec backend python -m app.cli backfill --start 2016-01-01
   ```
2. Fetch the second source for cross-checking (a few minutes):
   ```sh
   docker compose exec backend python -m app.cli crosscheck --start 2016-01-01
   ```
3. Build the data-quality reports:
   ```sh
   docker compose exec backend python -m app.cli quality
   ```
4. Every trading day after 7 pm IST, bring everything up to date:
   ```sh
   docker compose exec backend python -m app.cli daily
   ```

Then open http://localhost:3000/data for the quality reports and
http://localhost:3000/spot-check to compare any stock and date with your broker's
chart. "Give me 20 stock-dates to check" picks a sample for you.

## Layout

- `backend/`: Python API, database schema and migrations, market-data code
- `web/`: Next.js web app
- `docs/spec.md`: what Jeron must do; `docs/plans/`: one plan per milestone;
  `docs/decisions/`: why things are the way they are
