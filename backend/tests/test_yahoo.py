from datetime import UTC, date, datetime
from decimal import Decimal

from app.data.yahoo import parse_chart
from app.enums import CorporateActionType


def ts(day: date) -> int:
    # Yahoo stamps NSE daily bars at 09:15 IST (03:45 UTC).
    return int(datetime(day.year, day.month, day.day, 3, 45, tzinfo=UTC).timestamp())


def payload():
    days = [date(2024, 10, 25), date(2024, 10, 28), date(2024, 10, 29)]
    return {
        "chart": {
            "result": [
                {
                    "meta": {"gmtoffset": 19800},
                    "timestamp": [ts(d) for d in days],
                    "events": {
                        "splits": {
                            str(ts(days[1])): {
                                "date": ts(days[1]),
                                "numerator": 2.0,
                                "denominator": 1.0,
                                "splitRatio": "2:1",
                            }
                        },
                        "dividends": {
                            str(ts(days[2])): {"amount": 5.5, "date": ts(days[2])},
                        },
                    },
                    "indicators": {
                        "quote": [
                            {
                                # Split-adjusted, as Yahoo sends them.
                                "open": [1343.5, 1337.0, None],
                                "high": [1344.3499755859375, 1353.0, 1343.2],
                                "low": [1322.0, 1322.0999755859375, 1320.3],
                                "close": [1327.8499755859375, 1334.3499755859375, 1340.0],
                                "volume": [18597496, 10824350, 12008361],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def test_parse_chart_undoes_split_adjustment():
    history = parse_chart("RELIANCE", payload())
    assert [(b.trade_date, b.close, b.volume) for b in history.bars] == [
        (date(2024, 10, 25), Decimal("2655.70"), 9298748),
        (date(2024, 10, 28), Decimal("1334.35"), 10824350),
    ]  # the third bar has no open and is skipped
    assert history.bars[0].high == Decimal("2688.70")


def test_parse_chart_events():
    split, dividend = parse_chart("RELIANCE", payload()).actions
    assert split.action_type == CorporateActionType.SPLIT
    assert (split.ex_date, split.ratio_new, split.ratio_old) == (
        date(2024, 10, 28),
        Decimal("2.0"),
        Decimal("1.0"),
    )
    assert dividend.action_type == CorporateActionType.DIVIDEND
    assert dividend.amount == Decimal("5.5000")


def test_parse_chart_empty():
    assert parse_chart("X", {"chart": {"result": [], "error": None}}).bars == []
