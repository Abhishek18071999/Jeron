from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    analytics,
    backtests,
    dashboard,
    data,
    deals,
    fundamentals,
    health,
    journal,
    market,
    news,
    paper,
    plan,
    portfolio,
    scan,
    sections,
    settings,
    setup,
    stocks,
    watchlist,
)
from app.api.security import ApiGuard
from app.config import get_settings

app = FastAPI(title="Jeron API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET"],
    allow_headers=["*"],
)
# Added last, so it runs first: unknown hosts and requests without the token stop here.
app.add_middleware(ApiGuard)
app.include_router(health.router)
app.include_router(data.router)
app.include_router(scan.router)
app.include_router(backtests.router)
app.include_router(paper.router)
app.include_router(journal.router)
# Before the dashboard's /stocks/{symbol}.
app.include_router(stocks.router)
app.include_router(deals.router)
app.include_router(fundamentals.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(market.router)
app.include_router(portfolio.router)
app.include_router(plan.router)
app.include_router(watchlist.router)
app.include_router(settings.router)
app.include_router(sections.router)
app.include_router(news.router)
app.include_router(setup.router)
