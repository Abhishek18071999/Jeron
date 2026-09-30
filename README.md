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

## Layout

- `backend/`: Python API, database schema and migrations, market-data code
- `web/`: Next.js web app
- `docs/spec.md`: what Jeron must do; `docs/plans/`: one plan per milestone;
  `docs/decisions/`: why things are the way they are
