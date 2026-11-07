"""Quarterly results in the database: the filings listed in NSE's Financial Results CSVs,
downloaded from NSE's archive and stored point in time.

Only stocks that could be traded are loaded by default (median daily turnover of ₹5
crore in some year, the universe's liquidity floor), one filing per company and quarter:
consolidated when the company files one, else standalone. Downloaded XBRL files are
kept under the data folder, so a stopped run carries on where it stopped.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.data.fundamentals import (
    FIELDS,
    FilingRef,
    ResultsFormatError,
    name_key,
    parse_xbrl,
    symbols_by_name,
)
from app.data.http import FetchError, NotPublishedError
from app.data.store import NSE_BARS
from app.enums import Exchange
from app.fundamentals.health import Health, health
from app.fundamentals.score import FundScore, Quarter, known_quarters, score_with_history
from app.models import DailyBar, FinancialResult, Instrument
from app.news.job import liquid_years

IST = ZoneInfo("Asia/Kolkata")
OCF = "CashFlowsFromUsedInOperatingActivities"
Log = Callable[[str], None]
Fetch = Callable[[str], bytes]


def _quiet(_: str) -> None:
    pass


@dataclass
class ImportRun:
    filings: int = 0  # rows in the CSVs
    matched: int = 0  # rows of a known stock
    chosen: int = 0  # one per stock and quarter (and revision)
    stored: int = 0
    already: int = 0
    no_xbrl: int = 0
    failed: list[str] = field(default_factory=list)
    unmatched: set[str] = field(default_factory=set)


def cached_fetch(fetch: Fetch, folder: Path) -> Fetch:
    """`fetch`, keeping each file under `folder` so it is downloaded once."""

    def get(url: str) -> bytes:
        path = folder / url.rsplit("/", 1)[-1]
        if path.exists():
            return path.read_bytes()
        content = fetch(url)
        folder.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return content

    return get


def choose(refs: Iterable[FilingRef]) -> list[FilingRef]:
    """Consolidated filings when a company has them for a quarter, else standalone.
    Every revision of the chosen kind is kept (each is known from its own time)."""
    by_quarter: dict[tuple[str, date], list[FilingRef]] = {}
    for ref in refs:
        by_quarter.setdefault((ref.company, ref.period_end), []).append(ref)
    chosen = []
    for group in by_quarter.values():
        consolidated = [r for r in group if r.consolidated]
        chosen.extend(consolidated or group)
    return sorted(chosen, key=lambda r: (r.period_end, r.company, r.disseminated_at))


# Consecutive failed downloads (each already retried by the Fetcher) before an import
# stops: NSE is unreachable, and every further filing would wait out the same retries.
GIVE_UP_AFTER = 3


def import_results(
    session: Session,
    refs: Sequence[FilingRef],
    fetch: Fetch,
    *,
    all_stocks: bool = False,
    log: Log = _quiet,
) -> ImportRun:
    refs = list(dict.fromkeys(refs))  # files saved for overlapping dates repeat rows
    run = ImportRun(filings=len(refs))
    instruments = session.execute(
        select(Instrument.symbol, Instrument.name).where(Instrument.exchange == Exchange.NSE)
    ).all()
    known = {s for s, _ in instruments}
    by_name = symbols_by_name((s, n) for s, n in instruments)
    wanted = None if all_stocks else set(liquid_years(session))
    picked: list[tuple[str, FilingRef]] = []
    # A company renamed since it filed matches no current name: one of its filings says
    # its symbol (downloaded once, kept with the others).
    by_name.update(_symbols_from_filings(refs, by_name, known, fetch, log))
    for ref in refs:
        symbol = by_name.get(name_key(ref.company))
        if symbol is None:
            run.unmatched.add(ref.company)
            continue
        run.matched += 1
        if wanted is None or symbol in wanted:
            picked.append((symbol, ref))
    symbol_of = {(r.company, r.xbrl_url): s for s, r in picked}
    chosen = choose(r for _, r in picked)
    run.chosen = len(chosen)
    stored = set(
        session.scalars(
            select(FinancialResult.xbrl_url).where(
                FinancialResult.xbrl_url.in_([r.xbrl_url for r in chosen if r.xbrl_url])
            )
        )
    )
    fetch_failures = 0
    for n, ref in enumerate(chosen, start=1):
        if fetch_failures >= GIVE_UP_AFTER:
            run.failed.append(
                f"stopped after {GIVE_UP_AFTER} downloads failed in a row (is NSE reachable?);"
                " run the import again later, stored filings are kept"
            )
            break
        if ref.xbrl_url is None:
            run.no_xbrl += 1
            continue
        if ref.xbrl_url in stored:
            run.already += 1
            continue
        try:
            result = parse_xbrl(fetch(ref.xbrl_url), ref.period_end)
        except (FetchError, NotPublishedError, ResultsFormatError) as exc:
            fetch_failures = fetch_failures + 1 if isinstance(exc, FetchError) else 0
            run.failed.append(f"{ref.company} {ref.period_end}: {exc}")
            continue
        fetch_failures = 0
        symbol = symbol_of[(ref.company, ref.xbrl_url)]
        if result.symbol and result.symbol != symbol and result.symbol in known:
            symbol = result.symbol  # the filing's own symbol wins over the name match
        session.execute(
            pg_insert(FinancialResult)
            .values(
                symbol=symbol,
                company=ref.company[:200],
                period_start=result.period_start,
                period_end=result.period_end,
                consolidated=result.consolidated or ref.consolidated,
                audited=ref.audited,
                standard=ref.standard[:16],
                disseminated_at=ref.disseminated_at,
                xbrl_url=ref.xbrl_url,
                audit_opinion=(result.audit_opinion or "")[:500] or None,
                facts={k: str(v) for k, v in result.facts.items()},
                balance={k: str(v) for k, v in result.balance.items()},
                ytd={k: str(v) for k, v in result.ytd.items()},
                **{k: result.numbers.get(k) for k in FIELDS},
            )
            .on_conflict_do_nothing()
        )
        run.stored += 1
        if n % 50 == 0:
            session.commit()
            log(f"  {n} of {len(chosen)} filings read, {run.stored} stored.")
    session.commit()
    return run


@dataclass
class ReparseRun:
    rows: int = 0  # stored filings without balance-sheet or year-to-date facts
    updated: int = 0
    not_cached: int = 0
    failed: list[str] = field(default_factory=list)


def reparse_cached(
    session: Session, folder: Path, *, fetch: Fetch | None = None, log: Log = _quiet
) -> ReparseRun:
    """fundamentals-v2: fill the balance-sheet and year-to-date facts of filings stored
    before they were kept, from the XBRL files under `folder`. With `fetch`, a file not
    there is downloaded (and kept); without, it is counted and the filing left as it is."""
    run = ReparseRun()
    rows = session.scalars(
        select(FinancialResult).where(FinancialResult.balance == {}, FinancialResult.ytd == {})
    ).all()
    run.rows = len(rows)
    for n, row in enumerate(rows, start=1):
        path = folder / row.xbrl_url.rsplit("/", 1)[-1]
        if not path.exists() and fetch is None:
            run.not_cached += 1
            continue
        try:
            content = (
                path.read_bytes() if fetch is None else cached_fetch(fetch, folder)(row.xbrl_url)
            )
            result = parse_xbrl(content, row.period_end)
        except (FetchError, NotPublishedError, ResultsFormatError) as exc:
            run.failed.append(f"{row.symbol} {row.period_end}: {exc}")
            continue
        if result.balance or result.ytd:
            row.balance = {k: str(v) for k, v in result.balance.items()}
            row.ytd = {k: str(v) for k, v in result.ytd.items()}
            run.updated += 1
        if n % 500 == 0:
            session.commit()
            log(f"  {n} of {run.rows} filings read, {run.updated} updated.")
    session.commit()
    return run


def _symbols_from_filings(
    refs: Iterable[FilingRef],
    by_name: dict[str, str],
    known: set[str],
    fetch: Fetch,
    log: Log = _quiet,
) -> dict[str, str]:
    """name_key -> symbol for companies no current name matches, from the newest
    filing of each that has XBRL. Nothing is downloaded when no stock is known (none
    could match), and the lookup stops when downloads keep failing."""
    if not known:
        return {}
    newest: dict[str, FilingRef] = {}
    for ref in refs:
        k = name_key(ref.company)
        if k in by_name or ref.xbrl_url is None:
            continue
        if k not in newest or ref.disseminated_at > newest[k].disseminated_at:
            newest[k] = ref
    found = {}
    failures = 0
    for k, ref in newest.items():
        if failures >= GIVE_UP_AFTER:
            log(
                f"Renamed-company lookup stopped after {GIVE_UP_AFTER} downloads failed in a"
                " row; those companies stay unmatched this run."
            )
            break
        try:
            symbol = parse_xbrl(fetch(ref.xbrl_url or "")).symbol
        except FetchError:
            failures += 1
            continue
        except (NotPublishedError, ResultsFormatError):
            failures = 0
            continue
        failures = 0
        if symbol in known:
            found[k] = symbol
    return found


def _owners(row: FinancialResult) -> float | None:
    # Some filings leave the owners' share at 0 while reporting a profit.
    if row.profit_to_owners not in (None, 0):
        return float(row.profit_to_owners)
    return None if row.net_profit is None else float(row.net_profit)


def _shares(row: FinancialResult) -> float | None:
    if row.paid_up_capital is None or not row.face_value:
        return None
    return float(row.paid_up_capital / row.face_value)


def _f(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _fact(facts: dict[str, Any] | None, *names: str) -> float | None:
    for name in names:
        value = (facts or {}).get(name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _debt(balance: dict[str, Any] | None) -> float | None:
    parts = [_fact(balance, n) for n in ("BorrowingsCurrent", "BorrowingsNoncurrent")]
    if all(p is None for p in parts):
        return None
    return sum(p or 0.0 for p in parts)


def _ocf(row: FinancialResult) -> float | None:
    # The cash-flow statement is tagged year to date, or (in about one filing in six)
    # with the quarter's facts.
    ytd = _fact(row.ytd, OCF)
    return ytd if ytd is not None else _fact(row.facts, OCF)


def quarter_of(row: FinancialResult) -> Quarter:
    return Quarter(
        period_end=row.period_end,
        disseminated_at=row.disseminated_at,
        consolidated=row.consolidated,
        revenue=_f(row.revenue),
        net_profit=_owners(row),
        eps=_f(row.eps),
        financial=row.standard != "Ind-AS New",
        finance_costs=_f(row.finance_costs),
        depreciation=_f(row.depreciation),
        profit_before_tax=_f(row.profit_before_tax),
        other_income=_f(row.other_income),
        audit_opinion=row.audit_opinion,
        shares=_shares(row),
        equity=_fact(row.balance, "EquityAttributableToOwnersOfParent", "Equity"),
        debt=_debt(row.balance),
        cash=_fact(row.balance, "CashAndCashEquivalents"),
        ocf_ytd=_ocf(row),
    )


def filings(
    session: Session, symbols: Sequence[str], before: datetime | None = None
) -> dict[str, list[Quarter]]:
    """Every stored filing of each stock (revisions included), oldest published first."""
    query = select(FinancialResult).where(FinancialResult.symbol.in_(list(symbols)))
    if before is not None:
        query = query.where(FinancialResult.disseminated_at < before)
    out: dict[str, list[Quarter]] = {}
    for row in session.scalars(query.order_by(FinancialResult.disseminated_at)):
        out.setdefault(row.symbol, []).append(quarter_of(row))
    return out


def results_loaded(session: Session) -> bool:
    return session.scalar(select(FinancialResult.id).limit(1)) is not None


def quarters_known(
    session: Session, symbols: Sequence[str], as_of: datetime
) -> dict[str, list[Quarter]]:
    """Each stock's quarters as known at `as_of`: per quarter the latest filing
    disseminated before it, consolidated preferred. Oldest first."""
    return {
        symbol: known_quarters(rows, as_of)
        for symbol, rows in filings(session, symbols, as_of).items()
    }


# The stock page -----------------------------------------------------------------


@dataclass
class StockFundamentals:
    symbol: str
    as_of: date
    price: float | None
    score: FundScore
    quarters: list[Quarter]
    health: Health


def _closes(session: Session, symbol: str, days: Sequence[date]) -> dict[date, float]:
    """The raw close on or before each day (NSE bars)."""
    out: dict[date, float] = {}
    for day in days:
        close = session.scalar(
            select(DailyBar.close)
            .join(Instrument, Instrument.id == DailyBar.instrument_id)
            .where(
                Instrument.symbol == symbol,
                Instrument.exchange == Exchange.NSE,
                DailyBar.source == NSE_BARS,
                DailyBar.trade_date <= day,
            )
            .order_by(DailyBar.trade_date.desc())
            .limit(1)
        )
        if close is not None:
            out[day] = float(close)
    return out


def stock_fundamentals(
    session: Session, symbol: str, day: date | None = None
) -> StockFundamentals | None:
    """The fundamental score as known at the end of `day` (default today). None when no
    results are loaded for the stock."""
    day = day or datetime.now(IST).date()
    as_of = datetime.combine(day + timedelta(days=1), time(0), tzinfo=IST)
    quarters = quarters_known(session, [symbol], as_of).get(symbol, [])
    if not quarters:
        return None
    filed = [q.disseminated_at.date() for q in quarters]
    closes = _closes(session, symbol, [*filed[-20:], day])
    price = closes.get(day)
    return StockFundamentals(
        symbol,
        day,
        price,
        score_with_history(quarters, day, closes),
        quarters,
        health(quarters, day, price),
    )
