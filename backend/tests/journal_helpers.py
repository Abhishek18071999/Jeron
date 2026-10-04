"""Hand-made backtest runs, paper accounts and signals for journal tests."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.models import BacktestRun, PaperAccount, SignalRecord
from app.signals.build import IST


def make_account(
    session, key: str = "score-swing", live: bool = True, summary: dict | None = None
) -> PaperAccount:
    run = BacktestRun(
        strategy_key=key,
        strategy_version=f"{key}-v1",
        strategy_name=key,
        tier="swing",
        data_start=date(2016, 1, 1),
        data_end=date(2025, 6, 30),
        oos_start=date(2019, 1, 1),
        holdout_start=date(2024, 7, 1),
        live_eligible=live,
        fingerprint="test",
        summary=summary or {},
    )
    session.add(run)
    session.flush()
    account = PaperAccount(
        strategy_key=key,
        strategy_version=f"{key}-v1",
        params={},
        params_label="default",
        backtest_run_id=run.id,
        live_eligible=live,
        start_date=date(2025, 1, 1),
        capital=Decimal(1_000_000),
    )
    session.add(account)
    session.flush()
    return account


def make_signal(
    session,
    account: PaperAccount,
    ticker: str,
    day: date,
    valid_until: date,
    stop: Decimal = Decimal(90),
    research_only: bool = False,
) -> UUID:
    signal_id = uuid4()
    session.add(
        SignalRecord(
            signal_id=signal_id,
            account_id=account.id,
            ticker=ticker,
            signal_date=day,
            research_only=research_only,
            payload={
                "ticker": ticker,
                "tier": "swing",
                "entry_zone": {"low": "99", "high": "101", "valid_until": valid_until.isoformat()},
                "stop": {"price": str(stop)},
            },
            created_at=datetime(day.year, day.month, day.day, 19, tzinfo=IST),
        )
    )
    session.commit()
    return signal_id
