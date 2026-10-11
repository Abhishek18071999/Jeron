"""Quarterly financial results from NSE: the filing list and the XBRL filings.

- The list comes from the CSV that NSE's website offers on Corporate Filings >
  Financial Results (one row per filing: company, standalone or consolidated, period,
  the XBRL link and when NSE published it). The website turns scripts away, so the CSV
  is saved by hand; the filings themselves are on NSE's archive, which Jeron downloads.
- Each XBRL filing holds the quarter's profit and loss (context `OneD`; `FourD` is the
  year to date). Banks, NBFCs and other companies use different forms, so each number
  is read from the first of a few element names.

Point in time: a filing is known from the moment NSE disseminated it, which is stored
with it; a revised filing is a new row, never a change to the old one.

Pure module: the database layer stores what this returns.
"""

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
QUARTER = "OneD"

# Our field -> XBRL element names, first found wins (Ind-AS, NBFC, bank forms).
FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations", "Income"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income",),
    "finance_costs": ("FinanceCosts", "InterestExpended"),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "profit_before_tax": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
    "tax": ("TaxExpense",),
    "net_profit": ("ProfitLossForPeriod", "ProfitLossForThePeriod"),
    "profit_to_owners": (
        "ProfitOrLossAttributableToOwnersOfParent",
        "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
    ),
    "eps": (
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsPerShareAfterExtraordinaryItems",
        "BasicEarningsLossPerShareFromContinuingOperations",
    ),
    "paid_up_capital": ("PaidUpValueOfEquityShareCapital",),
    "face_value": ("FaceValueOfEquityShareCapital",),
    "gross_npa_pct": ("PercentageOfGrossNpa",),
}


class ResultsFormatError(ValueError):
    pass


@dataclass(frozen=True)
class FilingRef:
    """One row of NSE's Financial Results CSV."""

    company: str
    consolidated: bool
    audited: bool
    standard: str  # "Ind-AS New", "NBFC-IND", "Non-Ind-AS"
    period_end: date
    relating_to: str  # "Third Quarter"...
    xbrl_url: str | None  # None when NSE has no XBRL for the filing
    disseminated_at: datetime


@dataclass(frozen=True)
class QuarterResult:
    """The quarter's numbers from one XBRL filing. Rupees; EPS in rupees a share."""

    symbol: str | None
    isin: str | None
    period_start: date
    period_end: date
    consolidated: bool
    numbers: dict[str, Decimal]  # FIELDS keys that the filing has
    # Every numeric fact of the quarter, by element name, for later use.
    facts: dict[str, Decimal] = field(default_factory=dict)
    audit_opinion: str | None = None


def _clean(header: str) -> str:
    return re.sub(r"[^A-Z/ -]", "", header.upper()).strip()


def _date(text: str) -> date:
    return datetime.strptime(text.strip(), "%d-%b-%Y").date()


def _time(text: str) -> datetime:
    return datetime.strptime(text.strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)


def read_results_csv(text: str) -> list[FilingRef]:
    """The filings in a Financial Results CSV saved from nseindia.com."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = [_clean(h) for h in next(reader)]
    except StopIteration as exc:
        raise ResultsFormatError("the file is empty") from exc

    def col(name: str) -> int:
        for i, h in enumerate(header):
            if h.startswith(name):
                return i
        raise ResultsFormatError(
            f"no {name} column: is this the Financial Results CSV from nseindia.com?"
        )

    company, audited, consolidated = col("COMPANY NAME"), col("AUDITED"), col("CONSOLIDATED")
    standard, period_end, relating = col("IND AS"), col("PERIOD ENDED"), col("RELATING TO")
    xbrl, published = col("XBRL"), col("EXCHANGE DISSEMINATION TIME")
    period = col("PERIOD")
    refs = []
    for n, row in enumerate(reader, start=2):
        if not row or not any(c.strip() for c in row):
            continue
        if row[period].strip().lower() != "quarterly":
            continue  # half-yearly and annual rows repeat a quarter's numbers
        url = row[xbrl].strip()
        try:
            refs.append(
                FilingRef(
                    company=row[company].strip(),
                    consolidated=row[consolidated].strip().lower() == "consolidated",
                    audited=row[audited].strip().lower() == "audited",
                    standard=row[standard].strip(),
                    period_end=_date(row[period_end]),
                    relating_to=row[relating].strip(),
                    xbrl_url=None if not url.endswith(".xml") else url,
                    disseminated_at=_time(row[published]),
                )
            )
        except (ValueError, IndexError) as exc:
            raise ResultsFormatError(f"row {n}: {exc}") from exc
    return refs


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xbrl(content: bytes) -> QuarterResult:
    """The quarter's numbers from an NSE results XBRL filing."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ResultsFormatError(f"not XBRL: {exc}") from exc
    text: dict[str, str] = {}
    facts: dict[str, Decimal] = {}
    for el in root:
        if el.get("contextRef") != QUARTER or el.text is None:
            continue
        name = _local(el.tag)
        value = el.text.strip()
        if el.get("unitRef"):
            try:
                facts[name] = Decimal(value)
            except InvalidOperation:
                continue
        else:
            text[name] = value
    try:
        start = date.fromisoformat(text["DateOfStartOfReportingPeriod"])
        end = date.fromisoformat(text["DateOfEndOfReportingPeriod"])
    except (KeyError, ValueError) as exc:
        raise ResultsFormatError("the filing has no reporting period") from exc
    numbers = {}
    for key, names in FIELDS.items():
        for name in names:
            if name in facts:
                numbers[key] = facts[name]
                break
    nature = text.get("NatureOfReportStandaloneConsolidated", "")
    symbol = text.get("Symbol", "").strip().upper() or None
    return QuarterResult(
        symbol=None if symbol in (None, "NOTLISTED", "NA") else symbol,
        isin=text.get("ISIN") or None,
        period_start=start,
        period_end=end,
        consolidated=nature.lower().startswith("consolidated"),
        numbers=numbers,
        facts=facts,
        audit_opinion=text.get(
            "DeclarationOfUnmodifiedOpinionOrStatementOnImpactOfAuditQualification"
        ),
    )


# Company names ------------------------------------------------------------------

_SUFFIXES = ("LIMITED", "LTD")


def name_key(name: str) -> str:
    """A company name for matching: "V.S.T Tillers Tractors Limited" -> VSTTILLERSTRACTORS."""
    words = re.findall(r"[A-Z0-9]+", name.upper().replace("&", " AND "))
    while words and words[-1] in _SUFFIXES:
        words.pop()
    if words and words[0] == "THE":
        words.pop(0)
    return "".join(words)


def symbols_by_name(names: Iterable[tuple[str, str | None]]) -> dict[str, str]:
    """name_key -> symbol from (symbol, company name) pairs; names two stocks share are
    left out rather than guessed."""
    found: dict[str, str] = {}
    shared: set[str] = set()
    for symbol, name in names:
        if not name:
            continue
        k = name_key(name)
        if k in found and found[k] != symbol:
            shared.add(k)
        found[k] = symbol
    return {k: s for k, s in found.items() if k not in shared}
