"""Journal positions through splits and bonuses (pure).

Fills are stored as I made them: the shares and raw price of the day. A split or bonus
after a buy changes the share count the broker holds and the price NSE quotes, so a
position worked out from the stored fills alone is wrong from the ex-date on: 100 shares
bought at ₹200 before a 2:1 split are 200 shares quoted near ₹100, and marking 100
shares at ₹100 shows a loss that never happened, sizes the broker's stop for half the
shares, and refuses the sale of all 200.

Every consumer of fills therefore restates them to one basis first: each fill before an
ex-date has its shares multiplied by the action's ratio (shares after / shares before)
and its price divided so its cost is unchanged. Rupee amounts (cost, proceeds, charges,
gains, tax) don't move; only the share count and the per-share price do. A fractional
entitlement (a 1:2 bonus on an odd lot) is rounded down, as the broker pays it in cash.

Only share-count actions are restated. A rights issue or demerger leaves the shares held
unchanged; the exit plan still moves those prices with the price-only factor
(`app.exits.job`).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from app.data.adjust import SHARE_COUNT_ACTIONS, Adjustment
from app.journal.calc import Fill

ONE = Decimal(1)


@dataclass(frozen=True)
class ShareChange:
    ex_date: date
    ratio: Decimal  # shares after / shares before
    label: str  # "split 2:1", "bonus 1:1"


def share_changes(adjustments: Iterable[Adjustment]) -> list[ShareChange]:
    """The splits and bonuses among one stock's applied adjustments, oldest first."""
    out = []
    for adj in adjustments:
        a = adj.action
        if a.action_type not in SHARE_COUNT_ACTIONS or adj.factor <= 0:
            continue
        label = f"{a.action_type.value} {_n(a.ratio_new)}:{_n(a.ratio_old)}"
        out.append(ShareChange(adj.ex_date, ONE / adj.factor, label))
    return sorted(out, key=lambda c: c.ex_date)


def ratio_between(changes: Sequence[ShareChange], after: date, upto: date) -> Decimal:
    """Shares on `upto`'s basis for one share held at the close of `after`: the product
    of the ratios with an ex-date in (after, upto]."""
    ratio = ONE
    for c in changes:
        if after < c.ex_date <= upto:
            ratio *= c.ratio
    return ratio


def restate_fill(fill: Fill, ratio: Decimal) -> Fill:
    if ratio == ONE:
        return fill
    shares = int((fill.shares * ratio).to_integral_value(rounding=ROUND_FLOOR))
    if shares <= 0:
        return fill
    price = fill.price * fill.shares / shares
    return Fill(fill.trade_date, fill.side, shares, price, fill.charges)


def restate_fills(fills: Iterable[Fill], changes: Sequence[ShareChange], basis: date) -> list[Fill]:
    """`fills` on `basis`'s share basis (a fill on an ex-date is already on the new one)."""
    if not changes:
        return list(fills)
    return [restate_fill(f, ratio_between(changes, f.trade_date, basis)) for f in fills]


def restate_price(
    price: Decimal | None, changes: Sequence[ShareChange], since: date, basis: date
) -> Decimal | None:
    """A per-share price quoted on `since` (a stop) on `basis`'s share basis."""
    if price is None:
        return None
    ratio = ratio_between(changes, since, basis)
    return price if ratio == ONE else (price / ratio).quantize(Decimal("0.01"))


def basis_note(changes: Sequence[ShareChange], first: date | None, basis: date) -> str | None:
    """What was restated, for the journal: None when nothing was."""
    if first is None:
        return None
    hit = [c for c in changes if first < c.ex_date <= basis]
    if not hit:
        return None
    what = ", ".join(f"{c.label} (ex-date {c.ex_date:%d %b %Y})" for c in hit)
    return f"Shares and prices restated for the {what}; rupee amounts are unchanged."


def _n(value: Decimal | None) -> str:
    return "?" if value is None else f"{value.normalize():f}"
