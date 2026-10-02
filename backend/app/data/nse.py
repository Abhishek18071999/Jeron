"""NSE's official daily files: the equity bhavcopy and the "PR" market-data bundle.

- Bhavcopy: one row per security per day with raw (unadjusted) OHLC, volume and
  turnover. NSE switched format on 2024-07-08 from the legacy "cmDDMONYYYYbhav.csv"
  to the UDiFF "BhavCopy_NSE_CM_..." file. Both are parsed into the same `Bar`.
- PR bundle (PRddmmyy.zip): contains `bc<date>.csv`, NSE's list of upcoming
  corporate actions (ex-date and purpose, e.g. "BONUS 1:1"). Collected daily, these
  give a complete corporate-action history straight from the exchange. The
  bhavcopy's own previous-close column is not adjusted for these actions, so it
  cannot be used to infer them.

Downloads are cached on disk (raw bytes, unchanged), so history can be re-parsed
without downloading it again.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.data.http import Fetcher, NotPublishedError
from app.data.provider import (
    Bar,
    BarValidationError,
    CorporateActionRecord,
    validate_bar,
)
from app.enums import CorporateActionType

ARCHIVE = "https://nsearchives.nseindia.com"
UDIFF_START = date(2024, 7, 8)
# Mainboard equity series. SME (SM/ST), bonds, ETFs and the rest are not stored.
# BE and BZ are trade-for-trade and surveillance series; they are kept so a stock's
# history stays continuous when it moves between series, and M2's universe filter
# excludes them.
EQUITY_SERIES = frozenset({"EQ", "BE", "BZ"})
# Rights entitlements trade in the EQ series under symbols like "DUCON-RE1"; they are
# not shares and would pollute the price checks.
_RIGHTS_ENTITLEMENT = re.compile(r"-RE\d*$")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


class BhavcopyError(ValueError):
    pass


def bhavcopy_url(day: date) -> str:
    if day >= UDIFF_START:
        return f"{ARCHIVE}/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    mon = _MONTHS[day.month - 1]
    return (
        f"{ARCHIVE}/content/historical/EQUITIES/{day.year}/{mon}/"
        f"cm{day.day:02d}{mon}{day.year}bhav.csv.zip"
    )


def pr_url(day: date) -> str:
    return f"{ARCHIVE}/archives/equities/bhavcopy/pr/PR{day:%d%m%y}.zip"


def index_closes_url(day: date) -> str:
    """All NSE indices' closes for one day (parsed in `nse_lists`)."""
    return f"{ARCHIVE}/content/indices/ind_close_all_{day:%d%m%Y}.csv"


def security_list_url(day: date) -> str:
    """Price bands and surveillance remarks for one day (parsed in `nse_lists`)."""
    return f"{ARCHIVE}/content/equities/sec_list_{day:%d%m%Y}.csv"


@dataclass
class ParsedBhavcopy:
    trade_date: date
    bars: list[Bar] = field(default_factory=list)
    # (symbol, reason) for rows that failed validation and were not kept.
    rejected: list[tuple[str, str]] = field(default_factory=list)


def _dec(value: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise BhavcopyError(f"not a number: {value!r}") from exc


def _read_single_csv(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise BhavcopyError(f"expected one CSV in the zip, found {names}")
        return zf.read(names[0]).decode("utf-8-sig")


def parse_bhavcopy(content: bytes, expected_date: date) -> ParsedBhavcopy:
    """Parse a downloaded bhavcopy zip (either format) into raw bars."""
    text = _read_single_csv(content)
    header = text.split("\n", 1)[0]
    if header.startswith("TradDt"):
        return _parse_udiff(text, expected_date)
    if header.startswith("SYMBOL"):
        return _parse_legacy(text, expected_date)
    raise BhavcopyError(f"unknown bhavcopy header: {header[:80]!r}")


def _keep(parsed: ParsedBhavcopy, bar: Bar) -> None:
    if _RIGHTS_ENTITLEMENT.search(bar.symbol):
        return
    try:
        validate_bar(bar)
    except BarValidationError as exc:
        parsed.rejected.append((bar.symbol, str(exc)))
    else:
        parsed.bars.append(bar)


def _parse_legacy(text: str, expected_date: date) -> ParsedBhavcopy:
    parsed = ParsedBhavcopy(expected_date)
    for row in csv.DictReader(io.StringIO(text)):
        series = row["SERIES"].strip()
        if series not in EQUITY_SERIES:
            continue
        row_date = datetime.strptime(row["TIMESTAMP"].strip(), "%d-%b-%Y").date()
        if row_date != expected_date:
            raise BhavcopyError(f"file for {expected_date} contains rows dated {row_date}")
        symbol = row["SYMBOL"].strip()
        try:
            bar = Bar(
                symbol=symbol,
                trade_date=row_date,
                open=_dec(row["OPEN"]),
                high=_dec(row["HIGH"]),
                low=_dec(row["LOW"]),
                close=_dec(row["CLOSE"]),
                volume=int(row["TOTTRDQTY"]),
                prev_close=_dec(row["PREVCLOSE"]),
                turnover=_dec(row["TOTTRDVAL"]),
                series=series,
                isin=row.get("ISIN", "").strip() or None,
            )
        except (BhavcopyError, ValueError) as exc:
            parsed.rejected.append((symbol, str(exc)))
            continue
        _keep(parsed, bar)
    return parsed


def _parse_udiff(text: str, expected_date: date) -> ParsedBhavcopy:
    parsed = ParsedBhavcopy(expected_date)
    for row in csv.DictReader(io.StringIO(text)):
        series = row["SctySrs"].strip()
        if row["FinInstrmTp"] != "STK" or series not in EQUITY_SERIES:
            continue
        row_date = date.fromisoformat(row["TradDt"].strip())
        if row_date != expected_date:
            raise BhavcopyError(f"file for {expected_date} contains rows dated {row_date}")
        symbol = row["TckrSymb"].strip()
        try:
            bar = Bar(
                symbol=symbol,
                trade_date=row_date,
                open=_dec(row["OpnPric"]),
                high=_dec(row["HghPric"]),
                low=_dec(row["LwPric"]),
                close=_dec(row["ClsPric"]),
                volume=int(row["TtlTradgVol"]),
                prev_close=_dec(row["PrvsClsgPric"]),
                turnover=_dec(row["TtlTrfVal"]),
                series=series,
                isin=row["ISIN"].strip() or None,
            )
        except (BhavcopyError, ValueError) as exc:
            parsed.rejected.append((symbol, str(exc)))
            continue
        _keep(parsed, bar)
    return parsed


# --- Corporate actions from the PR bundle -------------------------------------------

_BC_NAME = re.compile(r"^bc\d+\.csv$", re.IGNORECASE)
_AMOUNT = r"(?:RS|RE|INR)\.?\s*([\d]+(?:\.\d+)?)"
# The new face value sometimes has no currency word: "FV SPLT FRM RS 10 TO 1".
_TO_AMOUNT = r"(?:(?:RS|RE|INR)\.?\s*)?([\d]+(?:\.\d+)?)"
_BONUS = re.compile(r"BONUS\s*(\d+)\s*:\s*(\d+)")
_SPLIT = re.compile(
    r"(?:SPLT|SPLIT|SUB[- ]?DIVISION|CONSOLIDATION|CONSOL)\D*?"
    + _AMOUNT
    + r"\D*?(?:TO|-)\s*"
    + _TO_AMOUNT
)
_RIGHTS = re.compile(r"(?:RIGHTS|RGHTS|RGTS)\s*(\d+)\s*:\s*(\d+)")
# Dividend wording varies: "DIV - RS 2 PER SH", "INTDVSPDVRS 7.50 & 86.50",
# "FIN DIV RS 6+SPL DIV RS 4", "DIV/SPDV - RS 2 & 1".
_DIVIDEND_WORD = re.compile(r"DIV|(?<![A-Z])DV|SPDV|INTDV")
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)(?!\s*%)(?![\d.])")
_OTHER_PRICE_EVENTS = (
    "DEMERGER",
    "CAPITAL REDUCTION",
    "SCHEME OF ARRANGEMENT",
    "RED OF CAP",
    "RIGHTS",
    "RGHTS",
)


def parse_purpose(symbol: str, ex_date: date, purpose: str) -> list[CorporateActionRecord]:
    """Turn NSE's purpose text into corporate actions that can move the price.

    Meetings, buybacks and interest payments return nothing. Anything price-moving
    that can't be parsed into numbers is returned as OTHER so it shows in the
    adjustment log instead of being silently dropped.
    """
    text = " ".join(purpose.upper().split())
    raw = purpose.strip()
    found: list[CorporateActionRecord] = []

    for bonus in _BONUS.finditer(text):
        new, held = int(bonus.group(1)), int(bonus.group(2))
        found.append(
            CorporateActionRecord(
                symbol,
                ex_date,
                CorporateActionType.BONUS,
                ratio_new=Decimal(new + held),
                ratio_old=Decimal(held),
                raw_text=raw,
            )
        )
    if split := _SPLIT.search(text):
        fv_from, fv_to = Decimal(split.group(1)), Decimal(split.group(2))
        if fv_from > 0 and fv_to > 0 and fv_from != fv_to:
            # Shares after / before = old face value / new face value.
            found.append(
                CorporateActionRecord(
                    symbol,
                    ex_date,
                    CorporateActionType.SPLIT,
                    ratio_new=fv_from,
                    ratio_old=fv_to,
                    raw_text=raw,
                )
            )
    if rights := _RIGHTS.search(text):
        found.append(
            CorporateActionRecord(
                symbol,
                ex_date,
                CorporateActionType.RIGHTS,
                ratio_new=Decimal(rights.group(1)),
                ratio_old=Decimal(rights.group(2)),
                raw_text=raw,
            )
        )
    rest = _RIGHTS.sub(" ", _SPLIT.sub(" ", _BONUS.sub(" ", text)))
    if (word := _DIVIDEND_WORD.search(rest)) and "DIVISION" not in rest:
        amounts = [Decimal(a) for a in _NUMBER.findall(rest[word.start() :])]
        found.append(
            CorporateActionRecord(
                symbol,
                ex_date,
                CorporateActionType.DIVIDEND,
                # None when the amount isn't given in rupees (e.g. "INTERIM DIVIDEND").
                amount=sum(amounts, Decimal(0)) if amounts else None,
                raw_text=raw,
            )
        )
    if not found and any(word in text for word in _OTHER_PRICE_EVENTS):
        kind = (
            CorporateActionType.RIGHTS
            if "RIGHTS" in text or "RGHTS" in text
            else CorporateActionType.OTHER
        )
        found.append(CorporateActionRecord(symbol, ex_date, kind, raw_text=raw))
    return found


def _parse_bc_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise BhavcopyError(f"unknown date format in corporate actions file: {value!r}")


def parse_pr_corporate_actions(content: bytes) -> list[CorporateActionRecord]:
    """Corporate actions listed in a PR bundle, for mainboard equity series."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if _BC_NAME.match(Path(n).name)]
        if not names:
            return []
        text = zf.read(names[0]).decode("latin-1")
    actions: list[CorporateActionRecord] = []
    seen: set[tuple[str, date, str]] = set()
    for raw in csv.DictReader(io.StringIO(text)):
        # A purpose containing a comma spills into extra fields; join it back.
        extra = raw.pop(None, None) or []
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if extra:
            row["PURPOSE"] = ",".join([row.get("PURPOSE", ""), *extra]).strip()
        if row.get("SERIES") not in EQUITY_SERIES:
            continue
        ex_date = _parse_bc_date(row.get("EX_DT", ""))
        if ex_date is None:
            continue
        key = (row["SYMBOL"], ex_date, row["PURPOSE"])
        if key in seen:
            continue
        seen.add(key)
        actions.extend(parse_purpose(row["SYMBOL"], ex_date, row["PURPOSE"]))
    return actions


# --- Download with an on-disk cache ---------------------------------------------------


class NseArchive:
    """Downloads NSE daily files once and keeps the raw bytes under `cache_dir`.

    A 404 for a day more than `settle_days` old is remembered as "not published"
    (a holiday); for recent days it is re-checked next time, because NSE publishes
    the day's files in the evening.
    """

    def __init__(self, fetcher: Fetcher, cache_dir: Path, settle_days: int = 3) -> None:
        self.fetcher = fetcher
        self.cache_dir = cache_dir
        self.settle_days = settle_days

    def _get(self, kind: str, url: str, day: date, today: date) -> bytes | None:
        path = self.cache_dir / "nse" / kind / str(day.year) / url.rsplit("/", 1)[1]
        missing = path.with_name(path.name + ".404")
        if path.exists():
            return path.read_bytes()
        if missing.exists():
            return None
        try:
            content = self.fetcher.get(url)
        except NotPublishedError:
            if day <= today - timedelta(days=self.settle_days):
                missing.parent.mkdir(parents=True, exist_ok=True)
                missing.touch()
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(content)
        tmp.replace(path)
        return content

    def bhavcopy(self, day: date, today: date) -> bytes | None:
        return self._get("bhavcopy", bhavcopy_url(day), day, today)

    def pr_bundle(self, day: date, today: date) -> bytes | None:
        return self._get("pr", pr_url(day), day, today)

    def index_closes(self, day: date, today: date) -> bytes | None:
        return self._get("indices", index_closes_url(day), day, today)

    def security_list(self, day: date, today: date) -> bytes | None:
        return self._get("sec_list", security_list_url(day), day, today)

    def current_list(self, url: str, today: date) -> bytes:
        """Download an undated list (always fresh) and keep a dated copy."""
        content = self.fetcher.get(url)
        path = self.cache_dir / "nse" / "lists" / today.isoformat() / url.rsplit("/", 1)[1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return content
