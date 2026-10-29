"""A real position held through a split or bonus (app/journal/basis.py): the shares
and prices are restated, rupee amounts are not, and every consumer (journal, exit plan,
broker stop, portfolio, equity curve, tax lots, adding a sale) sees the same position."""

from datetime import date, datetime
from decimal import Decimal

from app.calendar.nse import TradingCalendar
from app.config import Settings
from app.data import store
from app.data.adjust import Adjustment
from app.data.provider import CorporateActionRecord
from app.enums import CorporateActionType
from app.exits.job import broker_stop, build_preopen
from app.journal.basis import (
    ShareChange,
    basis_note,
    ratio_between,
    restate_fills,
    restate_price,
    share_changes,
)
from app.journal.calc import Fill, position
from app.journal.service import add_fill, entry_views, manual_entry, update_entry
from app.portfolio.calc import realised_sales
from app.portfolio.service import equity_history, portfolio
from app.signals.build import IST
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import _bar

D = date
SPLIT = ShareChange(D(2025, 7, 14), Decimal(2), "split 2:1")
BONUS = ShareChange(D(2025, 8, 4), Decimal("1.5"), "bonus 1:2")


def _action(kind: CorporateActionType, ex: date, new: int, old: int) -> CorporateActionRecord:
    return CorporateActionRecord("X", ex, kind, Decimal(new), Decimal(old))


# --- Pure ------------------------------------------------------------------------------


def test_share_changes_keep_only_splits_and_bonuses():
    split = _action(CorporateActionType.SPLIT, D(2025, 7, 14), 2, 1)
    bonus = _action(CorporateActionType.BONUS, D(2025, 8, 4), 3, 2)  # 1 new for 2 held
    rights = CorporateActionRecord("X", D(2025, 9, 1), CorporateActionType.RIGHTS)
    changes = share_changes(
        [
            Adjustment(bonus.ex_date, Decimal(2) / 3, bonus),
            Adjustment(split.ex_date, Decimal("0.5"), split),
            Adjustment(rights.ex_date, Decimal("0.97"), rights),
        ]
    )
    assert [(c.ex_date, c.ratio, c.label) for c in changes] == [
        (D(2025, 7, 14), Decimal(2), "split 2:1"),
        (D(2025, 8, 4), Decimal("1.5"), "bonus 3:2"),
    ]


def test_ratio_counts_ex_dates_after_the_day_up_to_the_basis():
    changes = [SPLIT, BONUS]
    assert ratio_between(changes, D(2025, 7, 1), D(2025, 9, 1)) == 3
    # A fill on the ex-date is already on the new basis.
    assert ratio_between(changes, D(2025, 7, 14), D(2025, 9, 1)) == Decimal("1.5")
    # A basis before the bonus doesn't count it (announced, not yet ex).
    assert ratio_between(changes, D(2025, 7, 1), D(2025, 8, 1)) == 2


def test_restated_fills_keep_cost_and_proceeds():
    fills = [
        Fill(D(2025, 7, 1), "buy", 101, Decimal("300"), Decimal("40")),
        Fill(D(2025, 7, 20), "buy", 10, Decimal("160")),  # after the split
        Fill(D(2025, 9, 2), "sell", 100, Decimal("110"), Decimal("20")),
    ]
    out = restate_fills(fills, [SPLIT, BONUS], D(2025, 9, 2))
    # 101 x 2 x 1.5 = 303; 10 x 1.5 = 15; the sale is after both.
    assert [f.shares for f in out] == [303, 15, 100]
    assert out[0].price == Decimal(100) and out[0].charges == Decimal(40)
    for before, after in zip(fills, out, strict=True):
        assert before.price * before.shares == after.price * after.shares
    # A 1:2 bonus on an odd lot: the half share is paid in cash, the cost stays whole.
    odd = restate_fills([Fill(D(2025, 7, 20), "buy", 5, Decimal("150"))], [BONUS], D(2025, 9, 2))
    assert odd[0].shares == 7 and (odd[0].price * 7).quantize(Decimal("0.01")) == 750


def test_restated_position_and_stop():
    fills = [Fill(D(2025, 7, 1), "buy", 100, Decimal("200"))]
    out = restate_fills(fills, [SPLIT], D(2025, 8, 1))
    stop = restate_price(Decimal("180"), [SPLIT], D(2025, 7, 1), D(2025, 8, 1))
    assert stop == Decimal("90.00")
    pos = position(out, stop, Decimal("100"))
    assert pos.held == 200 and pos.avg_entry == Decimal(100)
    assert pos.open_pnl == 0 and pos.r_multiple == 0
    # A stop set after the split isn't restated again.
    assert restate_price(Decimal("90"), [SPLIT], D(2025, 7, 20), D(2025, 8, 1)) == Decimal(90)


def test_tax_lots_match_a_sale_after_the_split():
    fills = restate_fills(
        [
            Fill(D(2025, 7, 1), "buy", 100, Decimal("200")),
            Fill(D(2025, 8, 1), "sell", 200, Decimal("110")),
        ],
        [SPLIT],
        D(2025, 8, 1),
    )
    (sale,) = realised_sales("X", fills)
    assert sale.shares == 200 and sale.gain == Decimal("2000.00")


def test_basis_note():
    assert basis_note([SPLIT], D(2025, 7, 1), D(2025, 6, 30)) is None
    assert basis_note([SPLIT], D(2025, 7, 20), D(2025, 9, 1)) is None
    note = basis_note([SPLIT, BONUS], D(2025, 7, 1), D(2025, 9, 1))
    assert note is not None and "split 2:1 (ex-date 14 Jul 2025)" in note
    assert "bonus 1:2" in note


# --- Database --------------------------------------------------------------------------

CAL = TradingCalendar.default()
DAYS = list(CAL.trading_days(date(2025, 6, 2), date(2025, 8, 29)))
EX = DAYS[30]


def _split_stock(s, last: int = 45) -> None:
    """SPL at ₹200, a 2:1 split on DAYS[30], ₹100 after it: no real change in value."""
    bars = [_bar("SPL", d, 200 if i < 30 else 100) for i, d in enumerate(DAYS[:last])]
    store.save_bars(s, store.NSE_BARS, bars)
    for d in DAYS[:last]:
        store.record_source_file(s, store.NSE_BARS, d, "ok")
    store.save_actions(
        s,
        store.NSE_ACTIONS,
        [CorporateActionRecord("SPL", EX, CorporateActionType.SPLIT, Decimal(2), Decimal(1))],
    )
    s.commit()


@requires_db
def test_held_through_a_split(empty_session):
    s = empty_session
    _split_stock(s)
    e = manual_entry(s, "SPL", stop=Decimal("180"))
    e.stop_set_on = DAYS[20]  # set on the buy day, before the split
    add_fill(s, e, DAYS[20], "buy", 100, Decimal("200"))
    s.commit()

    (v,) = entry_views(s, [e])
    assert v.position.held == 200 and v.position.avg_entry == Decimal(100)
    assert v.stop == Decimal("90.00") and v.position.open_pnl == 0
    assert v.basis_note is not None and "split 2:1" in v.basis_note

    # The exit plan and the broker's stop: 200 shares, the stop at ₹90 (not ₹45).
    p = build_preopen(s, DAYS[45], CAL)
    (c,) = p.positions
    assert c.shares == 200 and c.plan is not None
    assert c.plan.entry == 100 and c.plan.stop == 90

    pf = portfolio(s, DAYS[45], settings=Settings(), now=datetime(2025, 8, 5, 9, tzinfo=IST))
    (h,) = pf.holdings
    assert h.shares == 200 and h.value == Decimal(20000) and h.pnl == 0
    assert pf.account is not None and pf.account.drawdown_pct == 0

    # No fake loss on the ex-date.
    curve = equity_history(s, Decimal(1_000_000))
    assert {p.equity for p in curve.points} == {Decimal("1000000.00")}
    assert curve.max_drawdown_pct == 0

    # The broker sells 200 after the split: accepted, and the position closes flat.
    add_fill(s, e, DAYS[44], "sell", 200, Decimal("100"))
    (v,) = entry_views(s, [e])
    assert v.position.status == "closed" and v.position.realised_pnl == 0


@requires_db
def test_broker_stop_covers_every_share_after_the_split(empty_session):
    s = empty_session
    _split_stock(s)
    e = manual_entry(s, "SPL", stop=Decimal("190"))
    e.stop_set_on = DAYS[20]
    add_fill(s, e, DAYS[20], "buy", 100, Decimal("200"))
    s.commit()
    (c,) = build_preopen(s, DAYS[33], CAL).positions
    order = broker_stop(c)
    assert order is not None and order == (200, 95.0)


@requires_db
def test_a_stop_moved_after_the_split_is_not_restated(empty_session):
    s = empty_session
    _split_stock(s)
    e = manual_entry(s, "SPL", stop=Decimal("180"))
    add_fill(s, e, DAYS[20], "buy", 100, Decimal("200"))
    # Moved on a day after the ex-date, in the new prices.
    update_entry(
        s,
        e,
        decision="taken",
        reason="",
        stop=Decimal("92"),
        followed_plan=None,
        notes="",
    )
    assert e.stop_set_on is not None and e.stop_set_on > EX
    (v,) = entry_views(s, [e])
    assert v.stop == Decimal(92)
    # Saving the form again without changing the stop keeps its date.
    set_on = e.stop_set_on
    update_entry(s, e, decision="taken", reason="", stop=Decimal(92), followed_plan=None, notes="x")
    assert e.stop_set_on == set_on
