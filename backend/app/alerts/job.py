"""Send what is due after the daily run: one alert per new signal of a live-eligible
strategy (research-only ones too if the setting is on), one per watchlist alert price
reached, and the daily summary. Every alert is stored once; a re-run sends only what
failed before."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.channels import Channel, channels_from, deliver
from app.alerts.format import (
    Digest,
    DigestAccount,
    DigestPosition,
    digest_message,
    digest_signals,
    signal_message,
    watch_message,
)
from app.backtest.market import market_state
from app.config import Settings, get_settings
from app.data import store
from app.data.nse_lists import INDIA_VIX, NIFTY_50, NIFTY_500
from app.journal.service import entry_views, pending_signals
from app.models import (
    Alert,
    DataQualityReport,
    PaperAccount,
    ScanResult,
    ScanRun,
    SignalRecord,
)
from app.paper.job import latest_scan_date
from app.scan.score import SCORE_VERSION
from app.signals.build import IST
from app.watchlist.service import hits as watchlist_hits

Log = Callable[[str], None]
# Calendar days of index closes for the regime (200-day EMA) and VIX (5-year decile).
REGIME_HISTORY_DAYS = 2600
# Live signals this recent count as waiting for a decision in the summary.
PENDING_DAYS = 10
NOT_SET_UP = (
    "Alerts are not set up: set JERON_TELEGRAM_BOT_TOKEN and JERON_TELEGRAM_CHAT_ID "
    "(or JERON_SMTP_HOST and JERON_ALERT_EMAIL_TO) in .env."
)


def _quiet(_: str) -> None:
    pass


@dataclass
class AlertOutcome:
    day: date | None
    status: str  # "ok" / "not_configured" / "no_scan"
    sent: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    already_sent: int = 0


def regime_on(session: Session, day: date) -> tuple[str, bool] | None:
    """(regime, regime filter on) for the day, from stored index closes."""
    start = day - timedelta(days=REGIME_HISTORY_DAYS)
    n500 = store.index_closes(session, NIFTY_500, start, day)
    if not n500:
        return None
    days = sorted(n500)
    state = market_state(
        days,
        {d: float(v) for d, v in n500.items()},
        {d: float(v) for d, v in store.index_closes(session, NIFTY_50, start, day).items()},
        {d: float(v) for d, v in store.index_closes(session, INDIA_VIX, start, day).items()},
    )
    return None if state is None else (state.regime.value, state.risk_off)


def account_rows(session: Session) -> list[DigestAccount]:
    rows = []
    for a in session.scalars(
        select(PaperAccount).where(PaperAccount.status == "active").order_by(PaperAccount.id)
    ):
        s = a.summary or {}
        rows.append(
            DigestAccount(
                a.strategy_key,
                "paper" if a.live_eligible else "research only",
                Decimal(str(s.get("equity", a.capital))),
                Decimal(str(s.get("return_pct", 0))),
                int(s.get("open_positions", 0)),
                Decimal(str(s.get("heat_pct", 0))),
                Decimal(str(s.get("drawdown_pct", 0))),
            )
        )
    return rows


def day_signals(session: Session, day: date) -> list[tuple[SignalRecord, str]]:
    return [
        (r, key)
        for r, key in session.execute(
            select(SignalRecord, PaperAccount.strategy_key)
            .join(PaperAccount, PaperAccount.id == SignalRecord.account_id)
            .where(SignalRecord.signal_date == day)
            .order_by(SignalRecord.research_only, PaperAccount.id, SignalRecord.ticker)
        )
    ]


def build_digest(session: Session, day: date, web_url: str) -> Digest:
    report = session.scalar(select(DataQualityReport).where(DataQualityReport.trade_date == day))
    run = session.scalar(
        select(ScanRun).where(ScanRun.trade_date == day, ScanRun.score_version == SCORE_VERSION)
    )
    digest = Digest(
        day,
        None if report is None else report.status.value,
        [] if report is None else list(report.details.get("reasons", [])),
        web_url=web_url,
    )
    if run is not None:
        digest.scan_status = run.status
        digest.scan_reasons = list(run.details.get("reasons", []))
        digest.universe = run.universe_size
        digest.top = [
            (r.symbol, r.score)
            for r in session.scalars(
                select(ScanResult)
                .where(ScanResult.run_id == run.id)
                .order_by(ScanResult.rank)
                .limit(5)
            )
        ]
    regime = regime_on(session, day)
    if regime is not None:
        digest.regime, digest.risk_off = regime
    digest.signals = digest_signals(
        [(key, r.research_only, r.payload) for r, key in day_signals(session, day)]
    )
    digest.accounts = account_rows(session)
    digest.positions = [
        DigestPosition(v.entry.ticker, v.position.held, v.position.r_multiple)
        for v in entry_views(session, as_of=day)
        if v.position.status == "open"
    ]
    digest.pending = len(
        pending_signals(session, since=day - timedelta(days=PENDING_DAYS), include_research=False)
    )
    return digest


def _send(
    session: Session,
    channels: Sequence[Channel],
    key: str,
    kind: str,
    text: str,
    subject: str,
    outcome: AlertOutcome,
    now: datetime,
    day: date | None = None,
    signal_id: UUID | None = None,
) -> Alert:
    alert = session.scalar(select(Alert).where(Alert.key == key))
    if alert is not None and alert.status == "sent":
        outcome.already_sent += 1
        return alert
    if alert is None:
        alert = Alert(key=key, kind=kind, trade_date=day, signal_id=signal_id, attempts=0)
        session.add(alert)
    channel, errors = deliver(channels, text, subject)
    alert.text = text
    alert.attempts += 1
    alert.status = "sent" if channel else "failed"
    alert.channel = channel or (channels[-1].name if channels else None)
    alert.error = "; ".join(errors) or None
    alert.sent_at = now if channel else None
    session.commit()
    (outcome.sent if channel else outcome.failed).append(key)
    return alert


def run_alerts(
    session: Session,
    day: date | None = None,
    *,
    settings: Settings | None = None,
    channels: Sequence[Channel] | None = None,
    now: datetime | None = None,
    log: Log = _quiet,
) -> AlertOutcome:
    settings = settings or get_settings()
    channels = channels_from(settings) if channels is None else channels
    now = now or datetime.now(IST)
    day = day or latest_scan_date(session)
    if day is None:
        log("Alerts: no scan has run yet.")
        return AlertOutcome(None, "no_scan")
    if not channels:
        log(NOT_SET_UP)
        return AlertOutcome(day, "not_configured")
    outcome = AlertOutcome(day, "ok")
    for record, key in day_signals(session, day):
        if record.late or (record.research_only and not settings.alert_research_signals):
            continue
        text = signal_message(record.payload, record.research_only, settings.web_url)
        label = "Research only" if record.research_only else "Signal"
        _send(
            session,
            channels,
            f"signal:{record.signal_id}",
            "signal",
            text,
            f"Jeron {label}: {record.ticker} ({key})",
            outcome,
            now,
            day,
            record.signal_id,
        )
    for hit in watchlist_hits(session, day):
        _send(
            session,
            channels,
            hit.key,
            "watch",
            watch_message(
                hit.ticker,
                hit.direction,
                hit.price,
                hit.day,
                hit.high,
                hit.low,
                hit.close,
                hit.note,
                settings.web_url,
            ),
            f"Jeron watchlist: {hit.ticker} {hit.direction} {hit.price.normalize():f}",
            outcome,
            now,
            day,
        )
    digest = digest_message(build_digest(session, day, settings.web_url))
    _send(
        session,
        channels,
        f"digest:{day}",
        "digest",
        digest,
        f"Jeron daily summary {day}",
        outcome,
        now,
        day,
    )
    log(
        f"Alerts for {day}: {len(outcome.sent)} sent, {len(outcome.failed)} failed, "
        f"{outcome.already_sent} already sent"
    )
    for key in outcome.failed:
        alert = session.scalar(select(Alert).where(Alert.key == key))
        log(f"  - {key}: {alert.error if alert else ''}")
    return outcome


def send_test(
    session: Session,
    *,
    settings: Settings | None = None,
    channels: Sequence[Channel] | None = None,
    now: datetime | None = None,
) -> Alert | None:
    settings = settings or get_settings()
    channels = channels_from(settings) if channels is None else channels
    if not channels:
        return None
    now = now or datetime.now(IST)
    outcome = AlertOutcome(None, "ok")
    text = (
        "Jeron test message: alerts are working.\n"
        f"Sent {now:%a %-d %b %Y %H:%M} IST. Signals and the daily summary arrive here "
        "after each daily run."
    )
    return _send(
        session, channels, f"test:{now.isoformat()}", "test", text, "Jeron test", outcome, now
    )
