"""The backtester end to end on a real Postgres, with made-up stocks."""

import math
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.job import load_inputs, run_backtests
from app.backtest.market import build_market
from app.backtest.strategies import COMBINED, STRATEGIES
from app.config import get_settings
from app.data import store
from app.data.nse_lists import INDIA_VIX, NIFTY_50, NIFTY_500, IndexClose, SymbolChangeRecord
from app.data.provider import Bar, CorporateActionRecord
from app.db import get_engine
from app.enums import CorporateActionType
from app.main import app
from app.models import BacktestRun, BacktestTrade, BacktestVariant
from tests.backtest_helpers import weekdays
from tests.conftest import TEST_DATABASE_URL, requires_db, reset_database

pytestmark = requires_db

BACKEND_DIR = Path(__file__).resolve().parents[1]
DAYS = weekdays(date(2016, 1, 1), 1320)
SPLIT_DAY = DAYS[600]
RENAME_DAY = DAYS[500]
SYMBOLS = [f"STK{i}" for i in range(8)]


def _prices() -> dict[str, list[float]]:
    rng = np.random.default_rng(11)
    out = {}
    for symbol in [*SYMBOLS, "SPLITCO", "NEWNAME"]:
        out[symbol] = list(100 * np.exp(np.cumsum(rng.normal(0.0006, 0.02, len(DAYS)))))
    return out


def _bar(symbol: str, day: date, close: float, series: str = "EQ") -> Bar:
    c = Decimal(f"{close:.2f}")
    return Bar(
        symbol,
        day,
        c,
        (c * Decimal("1.01")).quantize(Decimal("0.01")),
        (c * Decimal("0.99")).quantize(Decimal("0.01")),
        c,
        1_000_000,
        turnover=c * 1_000_000,
        series=series,
    )


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("JERON_DATABASE_URL", TEST_DATABASE_URL or "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    reset_database(config)
    prices = _prices()
    with Session(get_engine()) as s:
        for i, day in enumerate(DAYS):
            bars = []
            for symbol, closes in prices.items():
                close = closes[i]
                if symbol == "SPLITCO" and day >= SPLIT_DAY:
                    close /= 2  # raw prices halve on the split
                name = "OLDNAME" if symbol == "NEWNAME" and day < RENAME_DAY else symbol
                bars.append(_bar(name, day, close))
            store.save_bars(s, store.NSE_BARS, bars)
            store.record_source_file(s, store.NSE_BARS, day, "ok", rows=len(bars))
            index = Decimal(f"{1000 * 1.0004**i:.2f}")
            store.save_index_closes(
                s,
                [
                    IndexClose(NIFTY_500, day, None, None, None, index),
                    IndexClose(NIFTY_50, day, None, None, None, index),
                    IndexClose(INDIA_VIX, day, None, None, None, Decimal("15")),
                ],
            )
        store.save_actions(
            s,
            store.NSE_ACTIONS,
            [
                CorporateActionRecord(
                    "SPLITCO",
                    SPLIT_DAY,
                    CorporateActionType.SPLIT,
                    Decimal(2),
                    Decimal(1),
                    raw_text="FV SPLT FRM RS 10 TO RS 5",
                ),
                CorporateActionRecord(
                    "STK1",
                    DAYS[700],
                    CorporateActionType.DIVIDEND,
                    amount=Decimal("2.5"),
                    raw_text="DIVIDEND RS 2.50",
                ),
            ],
        )
        store.save_symbol_changes(s, [SymbolChangeRecord("Co", "OLDNAME", "NEWNAME", RENAME_DAY)])
        s.commit()
        yield s
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_load_joins_renames_and_adjusts_splits(session):
    inputs = load_inputs(session)
    by_symbol = {s.symbol: s for s in inputs.stocks}
    assert "OLDNAME" not in by_symbol
    assert len(by_symbol["NEWNAME"].dates) == len(DAYS)
    split = by_symbol["SPLITCO"]
    i = DAYS.index(SPLIT_DAY)
    # Adjusted closes have no 50% gap; raw = adjusted / factor.
    assert split.close[i] / split.close[i - 1] == pytest.approx(
        _prices()["SPLITCO"][i] / _prices()["SPLITCO"][i - 1], rel=1e-3
    )
    assert split.factor[i - 1] == 0.5 and split.factor[i] == 1.0
    assert by_symbol["STK1"].dividends == {DAYS[700]: 2.5}
    market = build_market(inputs)
    assert market.universe.any()
    assert not math.isnan(np.nanmax(market.score))


def test_backtest_runs_are_stored_and_served(session):
    runs = run_backtests(session, ["breakout-52w"])
    assert len(runs) == 1
    run = runs[0]
    trades = session.scalar(select(func.count()).where(BacktestTrade.run_id == run.id))
    variants = session.scalar(select(func.count()).where(BacktestVariant.run_id == run.id))
    assert variants == 4 * (len(run.summary["schedule"]))
    assert (
        trades
        == run.summary["out_of_sample"]["trades"]["trades"]
        + run.summary["holdout"]["trades"]["trades"]
    )
    # A second run on the same data gives the same numbers and fingerprint.
    again = run_backtests(session, ["breakout-52w"])[0]
    assert again.id != run.id
    assert again.fingerprint == run.fingerprint
    assert again.summary == run.summary

    client = TestClient(app)
    latest = client.get("/backtests").json()
    assert [r["id"] for r in latest] == [again.id]
    view = client.get(f"/backtests/{run.id}").json()
    assert view["run"]["strategy_key"] == "breakout-52w"
    assert view["runs_of_strategy"] == 2
    assert len(view["equity"]) > 100
    rows = client.get(f"/backtests/{run.id}/trades", params={"segment": "oos"}).json()
    assert all(r["segment"] == "oos" for r in rows)
    assert client.get("/backtests/999999").status_code == 404
    assert session.scalar(select(func.count()).select_from(BacktestRun)) == 2


def test_every_strategy_runs_or_says_what_it_needs(session):
    """`backtest` with no strategy named: each one either runs and is stored, or is
    skipped with the input it lacks (no results calendar or fundamentals here)."""
    lines: list[str] = []
    runs = run_backtests(session, [*STRATEGIES, *COMBINED], log=lines.append)
    tested = {r.strategy_key for r in runs}
    skipped = {line.split(":")[0] for line in lines if ": skipped, " in line}
    assert tested | skipped == {*STRATEGIES, *COMBINED}
    assert skipped == {"results-drift", "quality-trend", "combined-book", "reversal"}
    assert any("run the events job" in line for line in lines)
    assert any("fundamentals-import" in line for line in lines)


def test_short_history_is_skipped_with_a_message(session):
    """With less history than the warm-up, `backtest` says so instead of a traceback."""
    lines: list[str] = []
    runs = run_backtests(session, ["breakout-52w"], start=DAYS[-30], log=lines.append)
    assert runs == []
    assert any("not enough history" in line for line in lines)
    assert session.scalar(select(func.count()).select_from(BacktestRun)) == 0


def test_review_research_options_run_and_are_not_saved(session):
    from sqlalchemy import func, select

    from app.backtest import research
    from app.backtest.job import load_inputs
    from app.backtest.market import build_market
    from app.models import BacktestRun

    market = build_market(load_inputs(session))
    rows = research.run_research(market, ["crash-guard", "no-time-stop", "quality"])
    assert [r.label for r in rows][1:] == [
        "Momentum-crash guard",
        "No time stop (warn only)",
        "Quality filter",
    ]
    assert rows[0].ev is not None and rows[1].ev is not None
    assert rows[3].ev is None and "fundamentals" in (rows[3].error or "")
    view = research.trial_view(market, rows[0].ev)
    assert 40 <= view.trials <= 60 and 1 <= view.effective <= view.trials
    text = research.report(rows, "test data", market, view)
    assert "Deflated Sharpe (item 7)" in text
    assert "rs-pullback-v1 as it is" in text and "Missed entries (item 10)" in text
    assert session.scalar(select(func.count()).select_from(BacktestRun)) == 0
