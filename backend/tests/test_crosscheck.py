from datetime import date
from decimal import Decimal

from app.data.crosscheck import Neighbours, compare_closes, compare_share_actions
from app.data.provider import CorporateActionRecord
from app.enums import CorporateActionType
from tests.helpers import bar

DAY = date(2024, 10, 28)


def test_compare_closes():
    nse = [
        bar("A", DAY, 100, 101, 99, 100),
        bar("B", DAY, 100, 101, 99, 100),
        bar("C", DAY, 100, 101, 99, 100),
    ]
    other = [bar("A", DAY, 100, 101, 99, 100.4), bar("B", DAY, 100, 102, 99, 101)]
    result = compare_closes(nse, other)
    assert result.checked == 2
    assert [(d.symbol, d.diff_pct) for d in result.mismatches] == [("B", Decimal("1.00"))]
    assert result.missing_in_secondary == ["C"]


def test_scaled_close_is_not_a_mismatch():
    # Yahoo's history is scaled by 0.2 for a later bonus its split list misses: every
    # neighbouring session shows the same factor, so the close agrees after scaling.
    nse = [bar("A", DAY, 500, 510, 490, 500), bar("B", DAY, 100, 101, 99, 100)]
    other = [bar("A", DAY, 100, 102, 98, 100.2), bar("B", DAY, 20, 21, 19, 21)]
    fifth = [Decimal("0.2"), Decimal("0.2001"), Decimal("0.1999"), Decimal("0.2")]
    neighbours = {"A": Neighbours(before=fifth, after=fifth), "B": Neighbours(before=fifth)}
    result = compare_closes(nse, other, neighbours=neighbours)
    assert result.checked == 2
    assert [(d.symbol, d.factor) for d in result.scaled] == [("A", Decimal("0.2"))]
    # B is 5% off the factor its neighbours show: a wrong close.
    assert [d.symbol for d in result.mismatches] == ["B"]


def test_factor_from_either_side_of_a_corporate_action():
    # On the day before a bonus Yahoo missed, the sessions after it already agree
    # (factor 1); the sessions before show the factor.
    nse = [bar("A", DAY, 500, 510, 490, 500)]
    other = [bar("A", DAY, 100, 102, 98, 100)]
    near = Neighbours(before=[Decimal("0.2")] * 5, after=[Decimal(1)] * 5)
    result = compare_closes(nse, other, neighbours={"A": near})
    assert [d.factor for d in result.scaled] == [Decimal("0.2")]
    assert result.mismatches == []


def test_too_few_neighbours_or_no_factor_stay_mismatches():
    nse = [bar("A", DAY, 500, 510, 490, 500), bar("B", DAY, 100, 101, 99, 100)]
    other = [bar("A", DAY, 100, 102, 98, 100), bar("B", DAY, 100, 102, 99, 103)]
    neighbours = {
        "A": Neighbours(before=[Decimal("0.2")] * 2, after=[Decimal("0.2")] * 2),
        # B's neighbours agree with NSE, so its 3% gap on the day is a bad close.
        "B": Neighbours(before=[Decimal(1)] * 10, after=[Decimal(1)] * 10),
    }
    result = compare_closes(nse, other, neighbours=neighbours)
    assert result.scaled == []
    assert [d.symbol for d in result.mismatches] == ["A", "B"]


def action(symbol, day, kind, new, old, text):
    return CorporateActionRecord(symbol, day, kind, Decimal(new), Decimal(old), raw_text=text)


def test_matching_bonus_and_split_agree():
    nse = [action("RELIANCE", DAY, CorporateActionType.BONUS, 2, 1, "BONUS 1:1")]
    yahoo = [action("RELIANCE", DAY, CorporateActionType.SPLIT, 2, 1, "split 2:1")]
    assert compare_share_actions(nse, yahoo, DAY, DAY) == []


def test_missing_or_different_actions_are_reported():
    nse = [
        action("A", DAY, CorporateActionType.SPLIT, 10, 2, "FVSPLT FRM RS 10 TO RS 2"),
        action("B", DAY, CorporateActionType.BONUS, 2, 1, "BONUS 1:1"),
    ]
    yahoo = [
        action("A", DAY, CorporateActionType.SPLIT, 2, 1, "split 2:1"),
        action("C", date(2024, 10, 29), CorporateActionType.SPLIT, 5, 1, "split 5:1"),
    ]
    problems = compare_share_actions(nse, yahoo, DAY, date(2024, 10, 31))
    assert sorted(p.symbol for p in problems) == ["A", "A", "B", "C"]


def test_bonus_and_split_on_one_day_compare_as_one():
    nse = [
        action("X", DAY, CorporateActionType.SPLIT, 10, 5, "FVSPLT FRM RS 10 TO RS 5"),
        action("X", DAY, CorporateActionType.BONUS, 2, 1, "BONUS 1:1"),
    ]
    yahoo = [action("X", date(2024, 10, 29), CorporateActionType.SPLIT, 4, 1, "split 4:1")]
    assert compare_share_actions(nse, yahoo, DAY, date(2024, 10, 31)) == []
