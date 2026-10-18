"""The Setup page: what Jeron has, what it is doing by itself (app/autopilot.py), and
the few things only the owner can do; plus uploads into the imports folder."""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import autopilot
from app.backtest.strategies import COMBINED, STRATEGIES, Combined, Strategy
from app.config import get_settings
from app.db import get_session
from app.models import (
    Announcement,
    BacktestRun,
    DailyBar,
    FinancialResult,
    PaperAccount,
)
from app.models import NewsLabel as NewsLabelRow
from app.news.job import labeller_name, missing_key
from app.news.labels import PROMPT_VERSION
from app.paper.job import latest_scan_date

router = APIRouter(tags=["setup"])
SessionDep = Annotated[Session, Depends(get_session)]
State = Literal["done", "working", "waiting", "you"]
MAX_UPLOAD = 60 * 2**20


class Step(BaseModel):
    key: str
    title: str
    state: State
    detail: str
    # Only when state is "you": what to do, one line each.
    todo: list[str] = []


class StrategyOut(BaseModel):
    key: str
    version: str
    name: str
    tier: str
    tested: datetime | None
    live_eligible: bool | None
    paper: bool


class SetupView(BaseModel):
    steps: list[Step]
    strategies: list[StrategyOut]
    autopilot: dict[str, Any]
    imports: dict[str, Any]
    imports_folder: str


def _env_line(settings: Any) -> str:
    name = {"deepseek": "DEEPSEEK", "ollama": "OLLAMA", "gemini": "GEMINI"}.get(
        settings.news_provider, "ANTHROPIC"
    )
    return f"JERON_{name}_API_KEY=your-key"


def _working(now: dict[str, Any] | None, *names: str) -> bool:
    return bool(now and now.get("step") in names)


@router.get("/setup")
def setup_view(session: SessionDep) -> SetupView:
    settings = get_settings()
    market = autopilot.market_status()
    imports = autopilot.imports_status()
    now = market["now"]
    steps: list[Step] = []

    first, last = session.execute(
        select(func.min(DailyBar.trade_date), func.max(DailyBar.trade_date))
    ).one()
    scanned = latest_scan_date(session)
    if _working(now, "backfill", "daily"):
        steps.append(Step(key="prices", title="Price history", state="working", detail=now["why"]))
    elif scanned:
        steps.append(
            Step(
                key="prices",
                title="Price history",
                state="done",
                detail=f"NSE prices {first} to {last}; latest scan {scanned}. Updated every "
                f"trading day at {settings.schedule_daily} IST while Jeron runs.",
            )
        )
    else:
        steps.append(
            Step(
                key="prices",
                title="Price history",
                state="waiting",
                detail="Starts by itself within a few minutes of Jeron starting.",
            )
        )

    count, latest = session.execute(
        select(func.count(Announcement.id), func.max(Announcement.day))
    ).one()
    labeller = labeller_name(settings)
    labelled = session.scalar(
        select(func.count(NewsLabelRow.id)).where(
            NewsLabelRow.labeller == labeller, NewsLabelRow.prompt_version == PROMPT_VERSION
        )
    )
    if _working(now, "events", "news"):
        steps.append(Step(key="news", title="News", state="working", detail=now["why"]))
    elif not settings.news_ready:
        steps.append(
            Step(
                key="news",
                title="News",
                state="you",
                detail=f"{count:,} announcements stored (latest {latest or 'none'}); they show "
                "on the stock pages and Today. " + missing_key(settings).split(":")[0] + ", so "
                "none is marked good or bad and the news filter is off.",
                todo=[
                    f"Open .env in the Jeron folder and set {_env_line(settings)} "
                    f"(JERON_NEWS_PROVIDER is {settings.news_provider}).",
                    "Run `docker compose up -d` in that folder (a restart doesn't read .env).",
                    "Jeron then labels the last 30 days by itself.",
                ],
            )
        )
    else:
        steps.append(
            Step(
                key="news",
                title="News",
                state="done" if count else "waiting",
                detail=f"{count:,} announcements stored (latest {latest or 'none'}), "
                f"{labelled:,} labelled by {labeller}. New ones are read after each daily run.",
            )
        )

    filings, newest = session.execute(
        select(func.count(FinancialResult.id), func.max(FinancialResult.period_end))
    ).one()
    busy = imports["running"] or imports["pending"]
    newer = (
        "The bundled lists end with the December 2024 quarter. For newer quarters, save a "
        "Financial Results CSV from nseindia.com (Companies Listed > Corporate Filings > "
        "Financial Results) and upload it below."
    )
    if busy:
        running = imports["running"]
        what = f"Importing {running['file']}" if running else "Waiting to import"
        steps.append(
            Step(
                key="results",
                title="Quarterly results",
                state="working",
                detail=f"{what}; {filings:,} quarters stored so far. Each filing is read from "
                "NSE at about one a second, so the first import takes some hours. It "
                "carries on after a restart.",
            )
        )
    elif filings:
        stale = newest is not None and (date.today() - newest).days > 200
        steps.append(
            Step(
                key="results",
                title="Quarterly results",
                state="you" if stale else "done",
                detail=f"{filings:,} quarters stored, newest ending {newest}.",
                todo=[newer] if stale else [],
            )
        )
    else:
        steps.append(
            Step(
                key="results",
                title="Quarterly results",
                state="waiting",
                detail="Jeron queues its bundled results lists (2016 to 2024) by itself.",
            )
        )

    runs: dict[str, tuple[datetime, bool]] = {}
    for version, created, eligible in session.execute(
        select(
            BacktestRun.strategy_version, BacktestRun.created_at, BacktestRun.live_eligible
        ).order_by(BacktestRun.created_at)
    ):
        runs[version] = (created, eligible)
    papers = set(
        session.scalars(
            select(PaperAccount.strategy_version).where(PaperAccount.status == "active")
        )
    )
    every: list[tuple[str, Strategy | Combined]] = [*STRATEGIES.items(), *COMBINED.items()]
    strategies = [
        StrategyOut(
            key=key,
            version=s.version,
            name=s.name,
            tier=s.tier.value,
            tested=runs[s.version][0] if s.version in runs else None,
            live_eligible=runs[s.version][1] if s.version in runs else None,
            paper=s.version in papers,
        )
        for key, s in every
    ]
    tested = sum(s.tested is not None for s in strategies)
    passed = sum(bool(s.live_eligible) for s in strategies)
    steps.append(
        Step(
            key="strategies",
            title="Strategies",
            state="working"
            if _working(now, "backtest", "paper")
            else ("done" if tested == len(strategies) else "waiting"),
            detail=(now["why"] + " " if _working(now, "backtest", "paper") else "")
            + f"{tested} of {len(strategies)} backtested, {passed} passed the section 6 "
            "gates and trade live; the rest are research only. Strategies that need results "
            "or news are tested once those are in.",
        )
    )

    alerts_ready = settings.telegram_ready or settings.email_ready
    steps.append(
        Step(
            key="alerts",
            title="Alerts on your phone",
            state="done" if alerts_ready else "you",
            detail="Telegram is set up."
            if settings.telegram_ready
            else (
                "Email alerts are set up."
                if settings.email_ready
                else "Not set up: signals only show here."
            ),
            todo=[]
            if alerts_ready
            else [
                "In Telegram, message @BotFather, send /newbot and copy the token it gives.",
                "Put JERON_TELEGRAM_BOT_TOKEN=that-token in .env and run `docker compose up -d`.",
                "Send your bot any message, then run `docker compose exec backend python -m "
                "app.cli telegram --setup` and put the JERON_TELEGRAM_CHAT_ID line it prints "
                "in .env.",
                "Run `docker compose up -d` again.",
            ],
        )
    )
    return SetupView(
        steps=steps,
        strategies=strategies,
        autopilot=market,
        imports=imports,
        imports_folder="the imports folder inside your Jeron folder",
    )


@router.get("/imports")
def imports_view() -> dict[str, Any]:
    return autopilot.imports_status()


@router.put("/imports/{name}")
async def upload(name: str, request: Request) -> dict[str, Any]:
    """Saves an uploaded file into the imports folder; the autopilot imports it."""
    clean = Path(name).name
    if not clean or clean.startswith(".") or Path(clean).suffix.lower() not in autopilot.IMPORTABLE:
        raise HTTPException(422, "Upload a .csv, .json or .zip file.")
    body = await request.body()
    if not body:
        raise HTTPException(422, f"{clean} is empty.")
    if len(body) > MAX_UPLOAD:
        raise HTTPException(413, f"{clean} is over {MAX_UPLOAD // 2**20} MB.")
    folder = autopilot.imports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / clean
    tmp = folder / f".upload-{clean}"
    tmp.write_bytes(body)
    tmp.replace(target)
    return {"saved": clean, "imports": autopilot.imports_status()}
