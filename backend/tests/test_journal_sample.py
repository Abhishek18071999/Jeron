"""Journal stats say how much a few trades can tell (app/journal/calc.py)."""

from decimal import Decimal

import pytest

from app.journal.calc import JournalRow, mean_interval, sample_note, strategy_stats, t95


def test_t_critical_values():
    assert t95(1) == 12.706 and t95(9) == 2.262 and t95(30) == 2.042
    assert t95(40) == pytest.approx(2.021, abs=0.003)  # tables: 2.021
    assert t95(120) == pytest.approx(1.980, abs=0.003)  # tables: 1.980
    with pytest.raises(ValueError):
        t95(0)


def test_mean_interval_by_hand():
    # R of 2, -1, -1, 2: mean 0.5, sample sd sqrt(3) = 1.7321, t(3) = 3.182.
    # Half width 3.182 x 1.7321 / 2 = 2.7557.
    low, high = mean_interval([Decimal(2), Decimal(-1), Decimal(-1), Decimal(2)])
    assert (low, high) == (Decimal("-2.2557"), Decimal("3.2557"))
    assert mean_interval([Decimal(1)]) is None
    assert mean_interval([]) is None


def test_sample_notes():
    assert sample_note(0, None) is None
    assert sample_note(1, None) == "1 closed trade: too few to judge (Jeron's gates want 30)."
    few = sample_note(4, (Decimal("-2.2557"), Decimal("3.2557")))
    assert few == (
        "4 closed trades: too few to judge (Jeron's gates want 30); the average R could be "
        "anywhere from -2.26R to 3.26R."
    )
    assert "still includes 0R" in (sample_note(40, (Decimal("-0.1"), Decimal("0.4"))) or "")
    assert sample_note(40, (Decimal("0.05"), Decimal("0.4"))) is None


def _closed(r: str) -> JournalRow:
    return JournalRow("rs-pullback", "taken", True, "closed", Decimal(r), Decimal(r) * 1000, 10)


def test_strategy_stats_carry_the_range():
    (s,) = strategy_stats([_closed("2"), _closed("-1"), _closed("-1"), _closed("2")])
    assert s.avg_r == Decimal("0.5000")
    assert (s.avg_r_low, s.avg_r_high) == (Decimal("-2.2557"), Decimal("3.2557"))
    assert s.sample_note is not None and s.sample_note.startswith("4 closed trades")
