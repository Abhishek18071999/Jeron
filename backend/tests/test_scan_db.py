"""The daily scan end to end on a real Postgres, with made-up stocks."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alembic import command
from app.config import get_settings
from app.data import store
from app.data.nse_lists import (
    NIFTY_500,
    IndexClose,
    IndexConstituent,
    SecurityStatusRecord,
    SymbolChangeRecord,
)
from app.data.provider import Bar, CorporateActionRecord
from app.db import get_engine
from app.enums import CorporateActionType, QualityStatus
from app.main import app
from app.models import DataQualityReport, IndexBar, ScanResult, ScanRun, SourceFile
from app.scan.job import ASM, run_scan
from tests.conftest import TEST_DATABASE_URL, requires_db

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _weekdays(start: date, n: int) -> list[date]:
    days, day = [], start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


DAYS = _weekdays(date(2025, 1, 1), 260)
LAST = DAYS[-1]
SPLIT_DAY = DAYS[200]
RENAME_DAY = DAYS[150]


def _bar(symbol, day, close, volume, series="EQ"):
    c = Decimal(str(round(close, 2)))
    return Bar(
        symbol,
        day,
        c,
        (c * Decimal("1.01")).quantize(Decimal("0.01")),
        (c * Decimal("0.99")).quantize(Decimal("0.01")),
        c,
        volume,
        turnover=c * volume,
        series=series,
    )


def _prices():
    """symbol -> {day: (close, volume, series)}"""
    p: dict[str, dict[date, tuple[float, int, str]]] = {}
    for i, day in enumerate(DAYS):
        p.setdefault("LEADER", {})[day] = (100 * 1.003**i, 1_000_000, "EQ")
        p.setdefault("LAGGER", {})[day] = (300 * 0.998**i, 1_000_000, "EQ")
        p.setdefault("TINY", {})[day] = (100.0, 1_000, "EQ")
        p.setdefault("PENNY", {})[day] = (10.0, 50_000_000, "EQ")
        p.setdefault("TTFT", {})[day] = (100.0, 1_000_000, "BE")
        p.setdefault("GSMCO", {})[day] = (100.0, 1_000_000, "EQ")
        p.setdefault("ASMCO", {})[day] = (100.0, 1_000_000, "EQ")
        if i >= 210:
            p.setdefault("NEWCO", {})[day] = (100.0 + i, 1_000_000, "EQ")
        if i < len(DAYS) - 1:
            p.setdefault("HALTED", {})[day] = (100.0, 1_000_000, "EQ")
        name = "OLDNAME" if day < RENAME_DAY else "RENAMED"
        p.setdefault(name, {})[day] = (200 * 1.001**i, 1_000_000, "EQ")
        # A steady riser with a 2:1 split: raw prices halve on SPLIT_DAY.
        raw = 400 * 1.002**i / (2 if day >= SPLIT_DAY else 1)
        p.setdefault("SPLITCO", {})[day] = (raw, 1_000_000, "EQ")
    return p


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("JERON_DATABASE_URL", TEST_DATABASE_URL or "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    with Session(get_engine()) as s:
        _load(s)
        yield s
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def _load(s: Session) -> None:
    prices = _prices()
    for day in DAYS:
        bars = [
            _bar(symbol, day, *values[day]) for symbol, values in prices.items() if day in values
        ]
        store.save_bars(s, store.NSE_BARS, bars)
        store.record_source_file(s, store.NSE_BARS, day, "ok", rows=len(bars))
        index = 1000 * 1.001 ** DAYS.index(day)
        store.save_index_closes(
            s, [IndexClose(NIFTY_500, day, None, None, None, Decimal(f"{index:.2f}"))]
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
            )
        ],
    )
    store.save_security_status(
        s,
        LAST,
        [
            SecurityStatusRecord("GSMCO", "EQ", Decimal(5), "GSM STAGE - I", "I"),
            SecurityStatusRecord("LEADER", "EQ", Decimal(20), None, None),
        ],
    )
    store.record_source_file(s, store.NSE_SEC_LIST, LAST, "ok", rows=2)
    store.replace_surveillance(s, ASM, {"ASMCO": "Stage I"}, LAST - timedelta(days=3), "manual")
    store.record_source_file(s, store.ASM_IMPORT, LAST - timedelta(days=3), "ok", rows=1)
    store.refresh_index_membership(
        s, NIFTY_500, [IndexConstituent("LEADER", "Leader Ltd", "Capital Goods", None)], DAYS[0]
    )
    store.save_symbol_changes(
        s, [SymbolChangeRecord("Renamed Ltd", "OLDNAME", "RENAMED", RENAME_DAY)]
    )
    s.add(DataQualityReport(trade_date=LAST, status=QualityStatus.WARN, details={"reasons": []}))
    s.commit()


def _results(s, run_id):
    return {r.symbol: r for r in s.scalars(select(ScanResult).where(ScanResult.run_id == run_id))}


@requires_db
def test_scan_builds_the_universe_and_scores_it(session):
    outcome = run_scan(session)
    assert outcome.status == "ok"
    assert outcome.trade_date == LAST
    results = _results(session, outcome.run_id)
    assert set(results) == {"LEADER", "LAGGER", "RENAMED", "SPLITCO"}
    assert outcome.universe_size == 4

    run = session.get(ScanRun, outcome.run_id)
    excluded = {e["rule"]: e for e in run.details["exclusions"]}
    assert excluded["low_turnover"]["count"] == 1  # TINY
    assert excluded["low_price"]["count"] == 1  # PENNY
    assert excluded["not_eq_series"]["count"] == 1  # TTFT
    assert excluded["gsm"]["symbols"] == ["GSMCO"]
    assert excluded["asm"]["symbols"] == ["ASMCO"]
    assert excluded["short_history"]["symbols"] == ["NEWCO"]
    # HALTED traded in the turnover window but not on the day.
    assert excluded["not_traded"]["count"] == 1
    assert run.details["security_list_date"] == str(LAST)
    assert run.details["notes"] == []

    leader, lagger = results["LEADER"], results["LAGGER"]
    assert leader.rank < lagger.rank
    assert leader.score > lagger.score
    assert leader.in_nifty500 and leader.sector == "Capital Goods"
    assert not lagger.in_nifty500
    assert {c["key"] for c in leader.components} >= {"trend_200", "rs_3m", "breakout"}
    assert leader.indicators["rs_3m"] > 0 > lagger.indicators["rs_3m"]

    # The renamed stock's history is joined across both symbols.
    assert results["RENAMED"].indicators["sessions"] == len(DAYS)
    # The split is adjusted: the stock sits at its high, not 50% below it.
    split = results["SPLITCO"]
    assert split.indicators["below_52w_high_pct"] < 2
    assert split.close == Decimal(str(round(400 * 1.002 ** (len(DAYS) - 1) / 2, 2)))


@requires_db
def test_rerun_replaces_the_days_results(session):
    first = run_scan(session)
    second = run_scan(session, LAST)
    assert session.scalar(select(func.count()).select_from(ScanRun)) == 1
    assert session.get(ScanRun, first.run_id) is None
    assert len(_results(session, second.run_id)) == 4


@requires_db
@pytest.mark.parametrize("problem", ["quality_fail", "no_quality", "no_index", "no_sec_list"])
def test_scan_refuses_when_data_is_not_trustworthy(session, problem):
    report = session.scalar(select(DataQualityReport))
    if problem == "quality_fail":
        report.status = QualityStatus.FAIL
        report.details = {"reasons": ["NSE file missing"]}
    elif problem == "no_quality":
        session.delete(report)
    elif problem == "no_index":
        session.execute(IndexBar.__table__.delete().where(IndexBar.trade_date == LAST))
    else:
        session.execute(
            SourceFile.__table__.delete().where(SourceFile.source == store.NSE_SEC_LIST)
        )
    session.commit()
    outcome = run_scan(session)
    assert outcome.status == "blocked"
    assert len(outcome.reasons) == 1
    assert _results(session, outcome.run_id) == {}
    if problem == "quality_fail":
        assert "NSE file missing" in outcome.reasons[0]


@requires_db
def test_scan_notes_a_missing_asm_list(session):
    session.execute(SourceFile.__table__.delete().where(SourceFile.source == store.ASM_IMPORT))
    session.commit()
    outcome = run_scan(session)
    run = session.get(ScanRun, outcome.run_id)
    assert outcome.status == "ok"
    assert "No ASM list has been imported" in run.details["notes"][0]


@requires_db
def test_scan_api(session):
    client = TestClient(app)
    assert client.get("/scan/latest").status_code == 404
    run_scan(session)

    latest = client.get("/scan/latest", params={"limit": 2}).json()
    assert latest["run"]["status"] == "ok"
    assert latest["run"]["trade_date"] == str(LAST)
    assert latest["total_results"] == 4
    assert [r["rank"] for r in latest["results"]] == [1, 2]
    assert latest["results"][0]["components"][0]["max_points"] == 15

    high = client.get("/scan/latest", params={"min_score": 99.9}).json()
    assert all(float(r["score"]) >= 99.9 for r in high["results"])

    assert client.get(f"/scan/{LAST}").json()["run"]["id"] == latest["run"]["id"]
    assert client.get("/scan/2020-01-01").status_code == 404
    runs = client.get("/scan/runs").json()
    assert [r["trade_date"] for r in runs] == [str(LAST)]
