"""NSE's other public files used by the scanner, all from the same archive server.

Dated daily files (kept for history, one per trading day):
- `ind_close_all_DDMMYYYY.csv`: every NSE index's open, high, low and close. Gives
  Nifty 500 (relative strength), Nifty 50 and India VIX (the regime filter).
- `sec_list_DDMMYYYY.csv`: every security's price band and surveillance remark,
  e.g. "GSM STAGE - I". Published from 2020.

Current lists (no history on the server, so Jeron keeps a dated copy of each
download and builds the history itself):
- `ind_nifty500list.csv`: today's Nifty 500 constituents and their industries.
- `EQUITY_L.csv`: every listed equity's name, ISIN and listing date.
- `symbolchange.csv`: every symbol rename since the 1990s.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.data.nse import ARCHIVE, EQUITY_SERIES
from app.data.provider import InstrumentRecord

NIFTY_500 = "Nifty 500"
NIFTY_50 = "Nifty 50"
INDIA_VIX = "India VIX"

NIFTY500_LIST_URL = f"{ARCHIVE}/content/indices/ind_nifty500list.csv"
EQUITY_LIST_URL = f"{ARCHIVE}/content/equities/EQUITY_L.csv"
SYMBOL_CHANGES_URL = f"{ARCHIVE}/content/equities/symbolchange.csv"


class ListFormatError(ValueError):
    pass


def _text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _rows(content: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(_text(content)))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _dec(value: str) -> Decimal | None:
    value = value.strip()
    if value in ("", "-"):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class IndexClose:
    index_name: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal


def parse_index_closes(content: bytes, expected_date: date) -> list[IndexClose]:
    rows = _rows(content)
    if rows and "Closing Index Value" not in rows[0]:
        raise ListFormatError(f"unknown index file columns: {list(rows[0])[:6]}")
    out = []
    for row in rows:
        close = _dec(row.get("Closing Index Value", ""))
        if not row.get("Index Name") or close is None or close <= 0:
            continue
        row_date = datetime.strptime(row["Index Date"], "%d-%m-%Y").date()
        if row_date != expected_date:
            raise ListFormatError(f"index file for {expected_date} has rows dated {row_date}")
        out.append(
            IndexClose(
                index_name=row["Index Name"],
                trade_date=row_date,
                open=_dec(row.get("Open Index Value", "")),
                high=_dec(row.get("High Index Value", "")),
                low=_dec(row.get("Low Index Value", "")),
                close=close,
            )
        )
    return out


@dataclass(frozen=True)
class SecurityStatusRecord:
    symbol: str
    series: str
    price_band: Decimal | None
    remarks: str | None
    gsm_stage: str | None


def parse_security_list(content: bytes) -> list[SecurityStatusRecord]:
    """Mainboard equity rows of a sec_list file. Remarks such as "GSM STAGE - I" or
    "GSM - Stage II" mark the Graded Surveillance Measure."""
    out = []
    for row in _rows(content):
        series = row.get("Series", "")
        if series not in EQUITY_SERIES or not row.get("Symbol"):
            continue
        text = row.get("Remarks", "").strip()
        remarks = None if text in ("", "-") else text
        gsm = None
        if remarks and "GSM" in remarks.upper():
            gsm = remarks.upper().replace("GSM", "").replace("STAGE", "").strip(" -") or "GSM"
        out.append(
            SecurityStatusRecord(
                symbol=row["Symbol"],
                series=series,
                price_band=_dec(row.get("Band", "")),
                remarks=remarks,
                gsm_stage=gsm,
            )
        )
    return out


@dataclass(frozen=True)
class IndexConstituent:
    symbol: str
    name: str
    industry: str | None
    isin: str | None


def parse_index_constituents(content: bytes) -> list[IndexConstituent]:
    rows = _rows(content)
    if not rows or "Symbol" not in rows[0]:
        raise ListFormatError("index constituent list has no Symbol column")
    return [
        IndexConstituent(
            symbol=r["Symbol"],
            name=r.get("Company Name", ""),
            industry=r.get("Industry") or None,
            isin=r.get("ISIN Code") or None,
        )
        for r in rows
        if r.get("Symbol")
    ]


def _listing_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def parse_equity_list(content: bytes) -> list[InstrumentRecord]:
    rows = _rows(content)
    if not rows or "SYMBOL" not in rows[0]:
        raise ListFormatError("equity list has no SYMBOL column")
    return [
        InstrumentRecord(
            symbol=r["SYMBOL"],
            isin=r.get("ISIN NUMBER") or None,
            name=r.get("NAME OF COMPANY") or None,
            series=r.get("SERIES") or "EQ",
            listing_date=_listing_date(r.get("DATE OF LISTING", "")),
        )
        for r in rows
        if r.get("SYMBOL")
    ]


@dataclass(frozen=True)
class SymbolChangeRecord:
    company_name: str | None
    old_symbol: str
    new_symbol: str
    change_date: date


def parse_symbol_changes(content: bytes) -> list[SymbolChangeRecord]:
    """symbolchange.csv: company name, old symbol, new symbol, date (no header row)."""
    out = []
    for row in csv.reader(io.StringIO(_text(content))):
        if len(row) < 4:
            continue
        old, new, when = (c.strip() for c in row[-3:])
        name = ",".join(c.strip() for c in row[:-3])  # a name may contain commas
        changed = _listing_date(when)
        if not old or not new or changed is None or old == new:
            continue
        out.append(SymbolChangeRecord(name or None, old, new, changed))
    return out
