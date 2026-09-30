"""Corporate-action price adjustment.

Raw prices are never changed. An adjusted series is computed on demand: every bar
before an action's ex-date is multiplied by that action's price factor, so the chart
has no artificial gap. Volumes are divided by the same factor.

- Splits and bonuses change the share count; their factor is exact
  (shares before / shares after), e.g. a 1:1 bonus halves earlier prices.
- Dividends are adjusted only when asked (a total-return series), with the usual
  factor 1 - dividend / previous close. Broker charts normally show split- and
  bonus-adjusted prices without dividend adjustment, so that is the default.
- Rights issues, demergers and other schemes are listed in the adjustment log but not
  applied: their factor needs the issue price or the value of the demerged business,
  which the exchange files don't give. The quality report flags the big price moves
  they cause, so they are visible rather than silently wrong.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.data.provider import Bar, CorporateActionRecord
from app.enums import CorporateActionType

SHARE_COUNT_ACTIONS = frozenset({CorporateActionType.SPLIT, CorporateActionType.BONUS})
PRICE_PLACES = Decimal("0.0001")


def price_factor(
    action: CorporateActionRecord,
    prev_close: Decimal | None = None,
    include_dividends: bool = False,
) -> Decimal | None:
    """Multiplier for prices before the ex-date, or None if the action isn't applied."""
    if action.action_type in SHARE_COUNT_ACTIONS:
        if action.ratio_new and action.ratio_old and action.ratio_new > 0:
            return action.ratio_old / action.ratio_new
        return None
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
    previous close that dividend factors need and settle revised ex-dates."""
    closes = [(b.trade_date, b.close) for b in bars]
    adjustments = []
    seen: set[tuple[date, CorporateActionType, Decimal]] = set()
    for action in actions:
        prev_close = None
        for day, close in reversed(closes):
            if day < action.ex_date:
                prev_close = close
                break
        factor = price_factor(action, prev_close, include_dividends)
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
