"""Who bought and sold a stock in size: NSE bulk and block deals, and insider trades.

- Bulk deals: one client trading more than 0.5% of a company's shares in a day.
  Block deals: a single trade of at least ₹10 crore in NSE's block window. NSE's
  archive publishes the current day's lists only (`bulk.csv`, `block.csv`), so the
  daily job keeps them; older ones load from the CSV NSE's website offers.
- Insider trades: SEBI (PIT) disclosures by promoters, directors and employees, from the
  CSV (or JSON) NSE's website offers. The PR bundle's announcements only say that a
  disclosure was made, not who traded how much.

These are facts about the past, published after the trades: a bulk deal the same
evening, an insider trade up to four trading days later. They are shown as information
on the stock page, not used as a signal (see docs/decisions/0011).

Pure module: the database layer stores what this returns.
"""

import csv
import io
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

BULK = "bulk"
BLOCK = "block"
BUY = "buy"
SELL = "sell"
ARCHIVE = "https://nsearchives.nseindia.com"
BULK_URL = f"{ARCHIVE}/content/equities/bulk.csv"
BLOCK_URL = f"{ARCHIVE}/content/equities/block.csv"


class DealFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Deal:
    day: date
    symbol: str
    kind: str  # BULK or BLOCK
    client: str
    side: str  # BUY or SELL
    quantity: int
    price: Decimal  # trade price, or the weighted average for a bulk deal
    remarks: str = ""

    @property
    def value(self) -> Decimal:
        return self.price * self.quantity


@dataclass(frozen=True)
class InsiderTrade:
    symbol: str
    person: str
    category: str  # "Promoters", "Promoter Group", "Director", "KMP", "Employees", ...
    side: str
    quantity: int
    value: Decimal | None
    traded_from: date | None
    traded_to: date | None
    disclosed: date  # when NSE published it: the day the market could know
    mode: str  # "Market Purchase", "Market Sale", "Off Market", "ESOP", "Gift", ...
    before_pct: Decimal | None = None
    after_pct: Decimal | None = None

    @property
    def is_promoter(self) -> bool:
        return "promoter" in self.category.lower()

    @property
    def on_market(self) -> bool:
        """Bought or sold on the exchange: the person chose the price. ESOPs, gifts,
        transfers within the promoter group and off-market deals say much less."""
        mode = self.mode.lower()
        return "market" in mode and "off" not in mode


# --- Parsing ---------------------------------------------------------------------------


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _columns(
    headers: Iterable[str], wanted: Mapping[str, Sequence[str]], required: Sequence[str]
) -> dict[str, str]:
    """Map each wanted field to the file's own header, by normalised name."""
    by_key = {_key(h): h for h in headers if h is not None}
    found = {}
    for name, aliases in wanted.items():
        for alias in aliases:
            if alias in by_key:
                found[name] = by_key[alias]
                break
    missing = [n for n in required if n not in found]
    if missing:
        raise DealFormatError(
            f"no column for {', '.join(missing)}; the file has: {', '.join(sorted(by_key))}"
        )
    return found


def _text(row: Mapping[str, object], column: str | None) -> str:
    if column is None:
        return ""
    value = row.get(column)
    return "" if value is None else " ".join(str(value).split())


def _day(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # "09-Oct-2026 19:41" and the like: the date is what matters.
    head = text.split(" ")[0] if " " in text else ""
    return _day(head) if head and head != text else None


def _number(text: str) -> Decimal | None:
    text = text.replace(",", "").strip()
    if text in ("", "-", "NA", "Nil", "nil"):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _side(text: str) -> str | None:
    word = text.strip().lower()
    if word.startswith(("buy", "purchase", "acqui")) or word == "b":
        return BUY
    if word.startswith(("sell", "sale", "dispos")) or word == "s":
        return SELL
    return None


_DEAL_COLUMNS = {
    "day": ("date", "bddtdate"),
    "symbol": ("symbol", "bdsymbol"),
    "client": ("clientname", "bdclientname"),
    "side": ("buysell", "bdbuysell"),
    "quantity": ("quantitytraded", "bdqtytrd"),
    "price": ("tradepricewghtavgprice", "tradeprice", "bdtpwatp"),
    "remarks": ("remarks", "bdremarks"),
}


def parse_deals(rows: Iterable[Mapping[str, object]], kind: str) -> list[Deal]:
    """Bulk or block deals from NSE's CSV (the archive's daily file or the download on
    NSE's website) or the website's JSON. Rows without a date, side or quantity, such as
    "NO RECORDS", are skipped."""
    if kind not in (BULK, BLOCK):
        raise ValueError(f"unknown deal kind {kind!r}")
    rows = list(rows)
    if not rows:
        return []
    cols = _columns(rows[0].keys(), _DEAL_COLUMNS, ("day", "symbol", "client", "side", "quantity"))
    deals: set[Deal] = set()
    for row in rows:
        day = _day(_text(row, cols["day"]))
        side = _side(_text(row, cols["side"]))
        quantity = _number(_text(row, cols["quantity"]))
        price = _number(_text(row, cols.get("price")))
        symbol = _text(row, cols["symbol"]).upper()
        if day is None or side is None or not quantity or price is None or not symbol:
            continue
        remarks = _text(row, cols.get("remarks"))
        deals.add(
            Deal(
                day=day,
                symbol=symbol,
                kind=kind,
                client=_text(row, cols["client"]).upper(),
                side=side,
                quantity=int(quantity),
                price=price,
                remarks="" if remarks == "-" else remarks,
            )
        )
    return sorted(deals, key=lambda d: (d.day, d.symbol, d.client, d.side, d.quantity))


_INSIDER_COLUMNS = {
    "symbol": ("symbol",),
    "person": ("nameoftheacquirerdisposer", "acqname"),
    "category": ("categoryofperson", "personcategory"),
    "security": (
        "typeofsecurityacquireddisplosed",
        "typeofsecurityacquireddisposed",
        "sectype",
    ),
    "quantity": (
        "noofsecuritiesacquireddisplosed",
        "noofsecuritiesacquireddisposed",
        "secacq",
    ),
    "value": (
        "valueofsecurityacquireddisplosed",
        "valueofsecurityacquireddisposed",
        "secval",
    ),
    "side": ("acquisitiondisposaltransactiontype", "tdptransactiontype"),
    "before_pct": ("shareholdingprior", "befacqsharesper"),
    "after_pct": ("post", "afteracqsharesper"),
    "traded_from": ("dateofallotmentacquisitionfrom", "acqfromdt"),
    "traded_to": ("dateofallotmentacquisitionto", "acqtodt"),
    "disclosed": ("broadcastedateandtime", "broadcastdateandtime", "date"),
    "mode": ("modeofacquisition", "acqmode"),
}


def is_insider_file(headers: Iterable[str]) -> bool:
    keys = {_key(h) for h in headers if h is not None}
    return bool(keys & set(_INSIDER_COLUMNS["person"]))


def parse_insider_trades(rows: Iterable[Mapping[str, object]]) -> list[InsiderTrade]:
    """Buys and sells of equity shares from NSE's insider-trading (SEBI PIT) disclosures,
    as the website's CSV download or JSON. Pledges, revocations and other securities are
    skipped: they are not trades."""
    rows = list(rows)
    if not rows:
        return []
    cols = _columns(
        rows[0].keys(),
        _INSIDER_COLUMNS,
        ("symbol", "person", "quantity", "side", "disclosed"),
    )
    trades: set[InsiderTrade] = set()
    for row in rows:
        security = _text(row, cols.get("security")).lower()
        if security and "equity" not in security:
            continue
        side = _side(_text(row, cols["side"]))
        quantity = _number(_text(row, cols["quantity"]))
        disclosed = _day(_text(row, cols["disclosed"]))
        symbol = _text(row, cols["symbol"]).upper()
        if side is None or not quantity or disclosed is None or not symbol:
            continue
        trades.add(
            InsiderTrade(
                symbol=symbol,
                person=_text(row, cols["person"]),
                category=_text(row, cols.get("category")),
                side=side,
                quantity=int(quantity),
                value=_number(_text(row, cols.get("value"))),
                traded_from=_day(_text(row, cols.get("traded_from"))),
                traded_to=_day(_text(row, cols.get("traded_to"))),
                disclosed=disclosed,
                mode=_text(row, cols.get("mode")),
                before_pct=_number(_text(row, cols.get("before_pct"))),
                after_pct=_number(_text(row, cols.get("after_pct"))),
            )
        )
    return sorted(trades, key=lambda t: (t.disclosed, t.symbol, t.person, t.side, t.quantity))


def read_file(
    content: bytes, name: str, kind: str | None = None
) -> tuple[list[Deal], list[InsiderTrade]]:
    """Deals or insider trades from a file saved from NSE's website: CSV, or the JSON its
    pages load (a list, or an object with a "data" list). Insider files are recognised by
    their columns; for deals, `kind` says bulk or block, else the file name must."""
    text = content.decode("utf-8-sig")
    rows: list[Mapping[str, object]]
    if text.lstrip()[:1] in ("[", "{"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("data", [])
        rows = [r for r in data if isinstance(r, dict)]
    else:
        rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return [], []
    if is_insider_file(rows[0].keys()):
        return [], parse_insider_trades(rows)
    if kind is None:
        lowered = name.lower()
        if "block" in lowered:
            kind = BLOCK
        elif "bulk" in lowered:
            kind = BULK
        else:
            raise DealFormatError(
                "can't tell bulk from block deals by the file name; say which with --kind"
            )
    return parse_deals(rows, kind), []


# --- Who bought and sold ---------------------------------------------------------------


@dataclass
class Party:
    """One client's bulk and block deals in one stock."""

    name: str
    bought_quantity: int = 0
    sold_quantity: int = 0
    bought_value: Decimal = Decimal(0)
    sold_value: Decimal = Decimal(0)
    deals: int = 0
    days: set[date] = field(default_factory=set)
    # Days on which it both bought and sold this stock.
    round_trip_days: set[date] = field(default_factory=set)
    kinds: set[str] = field(default_factory=set)
    last_day: date | None = None

    @property
    def net_value(self) -> Decimal:
        return self.bought_value - self.sold_value

    @property
    def net_quantity(self) -> int:
        return self.bought_quantity - self.sold_quantity

    @property
    def day_trader(self) -> bool:
        """Bought and sold the same day on at least half its days: an intraday or
        market-making firm moving volume, not an investor taking a position."""
        return 2 * len(self.round_trip_days) >= len(self.days)


def parties(deals: Iterable[Deal]) -> list[Party]:
    by_name: dict[str, Party] = {}
    sides: dict[tuple[str, date], set[str]] = defaultdict(set)
    for d in deals:
        p = by_name.setdefault(d.client, Party(d.client))
        if d.side == BUY:
            p.bought_quantity += d.quantity
            p.bought_value += d.value
        else:
            p.sold_quantity += d.quantity
            p.sold_value += d.value
        p.deals += 1
        p.days.add(d.day)
        p.kinds.add(d.kind)
        p.last_day = d.day if p.last_day is None else max(p.last_day, d.day)
        sides[(d.client, d.day)].add(d.side)
    for (client, day), seen in sides.items():
        if len(seen) == 2:
            by_name[client].round_trip_days.add(day)
    return sorted(by_name.values(), key=lambda p: (-abs(p.net_value), p.name))


@dataclass
class DealsSummary:
    buyers: list[Party]  # net buyers that kept the shares, biggest first
    sellers: list[Party]  # net sellers, biggest first
    day_traders: list[Party]  # bought and sold the same day; most deals first


def summarize_deals(deals: Iterable[Deal], top: int = 5) -> DealsSummary:
    everyone = parties(deals)
    holders = [p for p in everyone if not p.day_trader]
    buyers = sorted((p for p in holders if p.net_value > 0), key=lambda p: -p.net_value)
    sellers = sorted((p for p in holders if p.net_value < 0), key=lambda p: p.net_value)
    traders = sorted((p for p in everyone if p.day_trader), key=lambda p: (-p.deals, p.name))
    return DealsSummary(buyers[:top], sellers[:top], traders[:top])


@dataclass
class InsiderTotals:
    """Rupee value of insider buys and sells on the market, promoters apart from the
    rest. Trades without a value are counted but not summed."""

    promoter_bought: Decimal = Decimal(0)
    promoter_sold: Decimal = Decimal(0)
    others_bought: Decimal = Decimal(0)
    others_sold: Decimal = Decimal(0)
    on_market: int = 0
    # ESOPs, gifts, off-market and intra-group transfers.
    other_modes: int = 0

    @property
    def promoter_net(self) -> Decimal:
        return self.promoter_bought - self.promoter_sold

    @property
    def others_net(self) -> Decimal:
        return self.others_bought - self.others_sold


def insider_totals(trades: Iterable[InsiderTrade]) -> InsiderTotals:
    totals = InsiderTotals()
    for t in trades:
        if not t.on_market:
            totals.other_modes += 1
            continue
        totals.on_market += 1
        value = t.value or Decimal(0)
        if t.is_promoter:
            if t.side == BUY:
                totals.promoter_bought += value
            else:
                totals.promoter_sold += value
        elif t.side == BUY:
            totals.others_bought += value
        else:
            totals.others_sold += value
    return totals
