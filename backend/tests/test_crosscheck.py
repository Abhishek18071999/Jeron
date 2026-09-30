from datetime import date
from decimal import Decimal

from app.data.crosscheck import compare_closes, compare_share_actions
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
