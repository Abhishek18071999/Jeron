"""Corporate-action price adjustment.

Raw prices are never changed. An adjusted series is computed on demand: every bar
before an action's ex-date is multiplied by that action's price factor, so the chart
has no artificial gap. Volumes are divided by the same factor.

- Splits and bonuses change the share count; their factor is exact
  (shares before / shares after), e.g. a 1:1 bonus halves earlier prices.
- Dividends are adjusted only when asked (a total-return series), with the usual
  factor 1 - dividend / previous close. Broker charts normally show split- and
  bonus-adjusted prices without dividend adjustment, so that is the default.
- Rights issues (decision 0017) use the theoretical ex-rights price: with `n` new
  shares for every `h` held at issue price `S` and a previous close `P`, the factor is
  (h x P + n x S) / ((h + n) x P). The issue price is the premium in NSE's purpose
  text ("RGHTS 119:758 PRM RS 218"); the face value (₹1-10) is left out, which moves
  the factor by well under 1%. A rights issue priced at or above the previous close
  (nobody takes it up) and one without a ratio or a price are not applied.
- Demergers (decision 0017) use the price NSE's special pre-open session found on the
  ex-date: factor = ex-date open / previous close, as index providers do, because the
  demerged business has no price until it lists weeks later. A gap under 2% is left
  alone; so is a demerger whose ex-date has no bar.
- Other schemes (capital reduction, arrangements) are listed in the adjustment log but
  not applied. The quality report flags the big price moves they cause, so they are
  visible rather than silently wrong.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.data.provider import Bar, CorporateActionRecord
from app.enums import CorporateActionType

SHARE_COUNT_ACTIONS = frozenset({CorporateActionType.SPLIT, CorporateActionType.BONUS})
PRICE_PLACES = Decimal("0.0001")
FACTOR_PLACES = Decimal("0.000001")
# "PRM RS 218", "@ PREMIUM RS 1,201/-", "AT A PREM OF RS 49"; or the issue price itself,
# "@ RS 1200".
_RIGHTS_PRICE = re.compile(
    r"(?:PREMIUM|PREM|PRM)\.?\s*(?:OF\s*)?(?:RS|RE|INR)?\.?\s*(\d[\d,]*(?:\.\d+)?)"
    r"|@\s*(?:RS|RE|INR)\.?\s*(\d[\d,]*(?:\.\d+)?)"
)
# A demerger gap smaller than this is not adjusted (an ordinary day's move).
DEMERGER_MIN_GAP = Decimal("0.02")
# A price-implied factor below this is a data problem, not a demerger.
DEMERGER_MIN_FACTOR = Decimal("0.1")


def rights_issue_price(action: CorporateActionRecord) -> Decimal | None:
    """The rights issue's price per share: the stored amount, or the premium (or price)
    in the purpose text."""
    if action.amount and action.amount > 0:
        return action.amount
    match = _RIGHTS_PRICE.search((action.raw_text or "").upper())
    if match is None:
        return None
    value = Decimal((match.group(1) or match.group(2)).replace(",", ""))
    return value if value > 0 else None


def is_demerger(action: CorporateActionRecord) -> bool:
    return action.action_type == CorporateActionType.OTHER and "DEMERGER" in (
        action.raw_text or ""
    ).upper().replace(" ", "")


def rights_factor(action: CorporateActionRecord, prev_close: Decimal | None) -> Decimal | None:
    """Theoretical ex-rights price / previous close; None when it can't be worked out
    or the issue is priced at or above the market."""
    held, new, price = action.ratio_old, action.ratio_new, rights_issue_price(action)
    if not (held and new and price and prev_close) or held <= 0 or new <= 0 or prev_close <= 0:
        return None
    if price >= prev_close:
        return None
    factor = (held * prev_close + new * price) / ((held + new) * prev_close)
    return factor.quantize(FACTOR_PLACES)


def demerger_factor(prev_close: Decimal | None, ex_open: Decimal | None) -> Decimal | None:
    """Ex-date open / previous close (the special pre-open session's price); None for a
    gap under `DEMERGER_MIN_GAP`, a rise, or a factor too small to be real."""
    if not prev_close or not ex_open or prev_close <= 0 or ex_open <= 0:
        return None
    factor = (ex_open / prev_close).quantize(FACTOR_PLACES)
    if factor > 1 - DEMERGER_MIN_GAP or factor < DEMERGER_MIN_FACTOR:
        return None
    return factor


def price_factor(
    action: CorporateActionRecord,
    prev_close: Decimal | None = None,
    include_dividends: bool = False,
    ex_open: Decimal | None = None,
) -> Decimal | None:
    """Multiplier for prices before the ex-date, or None if the action isn't applied.
    Rights issues need `prev_close`; demergers need it and `ex_open`, the ex-date's
    opening price."""
    if action.action_type in SHARE_COUNT_ACTIONS:
        if action.ratio_new and action.ratio_old and action.ratio_new > 0:
            return action.ratio_old / action.ratio_new
        return None
    if action.action_type == CorporateActionType.RIGHTS:
        return rights_factor(action, prev_close)
    if is_demerger(action):
        return demerger_factor(prev_close, ex_open)
    if (
        action.action_type == CorporateActionType.DIVIDEND
        and include_dividends
        and action.amount
        and prev_close
        and 0 < action.amount < prev_close
    ):
        return 1 - action.amount / prev_close
    return None


@dataclass(frozen=True)
class Adjustment:
    ex_date: date
    factor: Decimal
    action: CorporateActionRecord


@dataclass(frozen=True)
class AdjustedBar:
    raw: Bar
    factor: Decimal  # cumulative multiplier applied to this bar's prices
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


# Two listings of the same split or bonus within this many days are treated as one
# action whose ex-date was revised; the price move decides which date is real.
DUPLICATE_WINDOW_DAYS = 45
# The ex-date open must be within this fraction of (previous close x factor).
CONFIRM_TOLERANCE = Decimal("0.15")


def confirmation_error(bars: Sequence[Bar], ex_date: date, factor: Decimal) -> Decimal | None:
    """How far the ex-date's opening gap is from what the factor predicts
    (0 = exactly as predicted). None if the bars around the ex-date are missing."""
    for i, bar in enumerate(bars):
        if bar.trade_date >= ex_date:
            if i == 0 or bar.trade_date != ex_date:
                return None
            expected = bars[i - 1].close * factor
            return abs(bar.open / expected - 1)
    return None


def price_confirms(bars: Sequence[Bar], ex_date: date, factor: Decimal) -> bool | None:
    error = confirmation_error(bars, ex_date, factor)
    return None if error is None else error <= CONFIRM_TOLERANCE


def _drop_revised_duplicates(
    bars: Sequence[Bar], adjustments: list[Adjustment]
) -> list[Adjustment]:
    kept: list[Adjustment] = []
    for adj in sorted(adjustments, key=lambda a: a.ex_date):
        if adj.action.action_type not in SHARE_COUNT_ACTIONS:
            kept.append(adj)
            continue
        twin = next(
            (
                k
                for k in kept
                if k.action.action_type == adj.action.action_type
                and k.factor == adj.factor
                and (adj.ex_date - k.ex_date).days <= DUPLICATE_WINDOW_DAYS
            ),
            None,
        )
        if twin is None:
            kept.append(adj)
            continue
        big = Decimal(1_000_000)
        twin_error = confirmation_error(bars, twin.ex_date, twin.factor)
        adj_error = confirmation_error(bars, adj.ex_date, adj.factor)
        if (adj_error if adj_error is not None else big) < (
            twin_error if twin_error is not None else big
        ):
            kept[kept.index(twin)] = adj
    return kept


def build_adjustments(
    bars: Sequence[Bar],
    actions: Iterable[CorporateActionRecord],
    include_dividends: bool = False,
) -> list[Adjustment]:
    """Adjustments for one symbol's actions. `bars` (raw, oldest first) supply the
    previous close that dividend and rights factors need, the ex-date open a demerger's
    needs, and settle revised ex-dates."""
    closes = [(b.trade_date, b.close) for b in bars]
    opens = {b.trade_date: b.open for b in bars}
    adjustments = []
    seen: set[tuple[date, CorporateActionType, Decimal]] = set()
    for action in actions:
        prev_close = None
        for day, close in reversed(closes):
            if day < action.ex_date:
                prev_close = close
                break
        factor = price_factor(action, prev_close, include_dividends, opens.get(action.ex_date))
        if factor is None or factor == 1:
            continue
        # The same action can be listed with slightly different wording.
        key = (action.ex_date, action.action_type, factor)
        if key in seen:
            continue
        seen.add(key)
        adjustments.append(Adjustment(action.ex_date, factor, action))
    return _drop_revised_duplicates(bars, adjustments)


def adjust_bars(bars: Sequence[Bar], adjustments: Sequence[Adjustment]) -> list[AdjustedBar]:
    """Apply adjustments to one symbol's raw bars (oldest first)."""
    result = []
    for bar in bars:
        factor = Decimal(1)
        for adj in adjustments:
            if adj.ex_date > bar.trade_date:
                factor *= adj.factor
        result.append(
            AdjustedBar(
                raw=bar,
                factor=factor,
                open=(bar.open * factor).quantize(PRICE_PLACES),
                high=(bar.high * factor).quantize(PRICE_PLACES),
                low=(bar.low * factor).quantize(PRICE_PLACES),
                close=(bar.close * factor).quantize(PRICE_PLACES),
                volume=round(bar.volume / factor),
            )
        )
    return result
