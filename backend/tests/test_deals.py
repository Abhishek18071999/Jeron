"""Bulk and block deals and insider trades: parsing NSE's files, and who bought and sold."""

import csv
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.deals import (
    BLOCK,
    BULK,
    BUY,
    SELL,
    Deal,
    DealFormatError,
    InsiderTrade,
    insider_totals,
    parse_deals,
    parse_insider_trades,
    read_file,
    summarize_deals,
)

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 10, 9)


def _rows(text: str):
    return list(csv.DictReader(io.StringIO(text)))


def test_archive_bulk_file():
    text = (FIXTURES / "nse_bulk_2026-10-09.csv").read_text()
    deals = parse_deals(_rows(text), BULK)
    assert len(deals) == 8
    jump = [d for d in deals if d.client.startswith("JUMP TRADING")]
    assert {(d.side, d.quantity, d.price) for d in jump} == {
        (BUY, 2362529, Decimal("30.45")),
        (SELL, 2897981, Decimal("30.60")),
    }
    assert all(d.day == DAY and d.kind == BULK and d.remarks == "" for d in deals)


def test_no_records_file_is_empty():
    text = (FIXTURES / "nse_block_empty.csv").read_text()
    assert parse_deals(_rows(text), BLOCK) == []


def test_website_download_with_spaced_headers_and_indian_commas():
    text = (
        '"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ","Quantity Traded ",'
        '"Trade Price / Wght. Avg. Price ","Remarks "\n'
        '"12-Mar-2025","HDFCBANK","HDFC Bank Ltd","SOCIETE GENERALE","SELL","1,23,45,678",'
        '"1,701.50","-"\n'
    )
    [deal] = parse_deals(_rows(text), BLOCK)
    assert deal == Deal(
        date(2025, 3, 12), "HDFCBANK", BLOCK, "SOCIETE GENERALE", SELL, 12345678, Decimal("1701.50")
    )
    assert deal.value == Decimal("1701.50") * 12345678


def test_website_json():
    data = {
        "data": [
            {
                "BD_DT_DATE": "12-Mar-2025",
                "BD_SYMBOL": "abc",
                "BD_SCRIP_NAME": "ABC Ltd",
                "BD_CLIENT_NAME": "Some Fund",
                "BD_BUY_SELL": "BUY",
                "BD_QTY_TRD": 1000,
                "BD_TP_WATP": 99.5,
                "BD_REMARKS": None,
            }
        ]
    }
    deals, insider = read_file(json.dumps(data).encode(), "deals.json", BULK)
    assert insider == []
    assert deals == [Deal(date(2025, 3, 12), "ABC", BULK, "SOME FUND", BUY, 1000, Decimal("99.5"))]


def test_kind_comes_from_the_file_name():
    text = (FIXTURES / "nse_bulk_2026-10-09.csv").read_bytes()
    assert {d.kind for d in read_file(text, "Block-Deals-01-01-2025.csv")[0]} == {BLOCK}
    with pytest.raises(DealFormatError, match="--kind"):
        read_file(text, "deals.csv")


def test_missing_columns_are_named():
    with pytest.raises(DealFormatError, match="client"):
        parse_deals(_rows("Date,Symbol,Buy/Sell,Quantity Traded\n09-OCT-2026,A,BUY,1\n"), BULK)


INSIDER_CSV = (
    '"SYMBOL \n","COMPANY \n","REGULATION \n","NAME OF THE ACQUIRER/DISPOSER \n",'
    '"CATEGORY OF PERSON \n","TYPE OF SECURITY (PRIOR) \n","NO. OF SECURITY (PRIOR) \n",'
    '"% SHAREHOLDING (PRIOR) \n","TYPE OF SECURITY (ACQUIRED/DISPLOSED) \n",'
    '"NO. OF SECURITIES (ACQUIRED/DISPLOSED) \n","VALUE OF SECURITY (ACQUIRED/DISPLOSED) \n",'
    '"ACQUISITION/DISPOSAL TRANSACTION TYPE \n","TYPE OF SECURITY (POST) \n",'
    '"NO. OF SECURITY (POST) \n","% POST \n","DATE OF ALLOTMENT/ACQUISITION FROM \n",'
    '"DATE OF ALLOTMENT/ACQUISITION TO \n","DATE OF INITMATION TO COMPANY \n",'
    '"MODE OF ACQUISITION \n","EXCHANGE \n","REMARK \n","BROADCASTE DATE AND TIME \n"\n'
    '"ABC","ABC Ltd","7(2)","Ravi Kumar","Promoters","Equity Shares","1,00,000","10.00",'
    '"Equity Shares","5,000","5,00,000","Buy","Equity Shares","1,05,000","10.50",'
    '"01-Oct-2026","03-Oct-2026","04-Oct-2026","Market Purchase","NSE","-",'
    '"07-Oct-2026 18:20"\n'
    '"ABC","ABC Ltd","7(2)","Asha Rao","Director","Equity Shares","2,000","0.20",'
    '"Equity Shares","2,000","-","Sell","Equity Shares","0","0.00",'
    '"02-Oct-2026","02-Oct-2026","03-Oct-2026","Market Sale","NSE","-","06-Oct-2026 17:00"\n'
    '"ABC","ABC Ltd","7(2)","Ravi Kumar","Promoters","Equity Shares","1,05,000","10.50",'
    '"Equity Shares","50,000","-","Pledge Creation","Equity Shares","1,05,000","10.50",'
    '"05-Oct-2026","05-Oct-2026","06-Oct-2026","-","NSE","-","08-Oct-2026 10:00"\n'
    '"ABC","ABC Ltd","7(2)","Staff One","Employees","Equity Shares","0","0",'
    '"Equity Shares","300","30,000","Buy","Equity Shares","300","0.03",'
    '"05-Oct-2026","05-Oct-2026","06-Oct-2026","ESOP","NSE","-","08-Oct-2026 11:00"\n'
)


def test_insider_csv():
    deals, trades = read_file(INSIDER_CSV.encode(), "CF-Insider-Trading-equities.csv")
    assert deals == []
    assert len(trades) == 3  # the pledge is not a trade
    ravi = next(t for t in trades if t.person == "Ravi Kumar")
    assert ravi == InsiderTrade(
        symbol="ABC",
        person="Ravi Kumar",
        category="Promoters",
        side=BUY,
        quantity=5000,
        value=Decimal(500000),
        traded_from=date(2026, 10, 1),
        traded_to=date(2026, 10, 3),
        disclosed=date(2026, 10, 7),
        mode="Market Purchase",
        before_pct=Decimal("10.00"),
        after_pct=Decimal("10.50"),
    )
    assert ravi.is_promoter and ravi.on_market
    asha = next(t for t in trades if t.person == "Asha Rao")
    assert asha.side == SELL and asha.value is None and not asha.is_promoter


def test_insider_json():
    rows = [
        {
            "symbol": "ABC",
            "acqName": "Ravi Kumar",
            "personCategory": "Promoter Group",
            "secType": "Equity Shares",
            "secAcq": "5000",
            "secVal": "500000",
            "tdpTransactionType": "Sell",
            "befAcqSharesPer": "10",
            "afterAcqSharesPer": "9.5",
            "acqfromDt": "01-Oct-2026",
            "acqtoDt": "01-Oct-2026",
            "date": "07-Oct-2026 18:20",
            "acqMode": "Off Market",
        }
    ]
    [t] = parse_insider_trades(rows)
    assert (t.side, t.disclosed, t.is_promoter, t.on_market) == (
        SELL,
        date(2026, 10, 7),
        True,
        False,
    )


def _deal(client, side, qty, price, day=DAY, kind=BULK):
    return Deal(day, "ABC", kind, client, side, qty, Decimal(price))


def test_same_day_traders_are_kept_apart_from_buyers_and_sellers():
    deals = [
        # A trading firm: in and out the same day, twice.
        _deal("HFT LLP", BUY, 1000, "100"),
        _deal("HFT LLP", SELL, 1000, "101"),
        _deal("HFT LLP", BUY, 500, "99", day=date(2026, 10, 8)),
        _deal("HFT LLP", SELL, 500, "98", day=date(2026, 10, 8)),
        # A fund building a position on two days, and a promoter selling a block.
        _deal("BIG FUND", BUY, 3000, "100"),
        _deal("BIG FUND", BUY, 2000, "95", day=date(2026, 9, 1)),
        _deal("SMALL FUND", BUY, 100, "100"),
        _deal("PROMOTER CO", SELL, 10000, "90", day=date(2026, 9, 1), kind=BLOCK),
    ]
    summary = summarize_deals(deals)
    assert [p.name for p in summary.buyers] == ["BIG FUND", "SMALL FUND"]
    big = summary.buyers[0]
    assert (big.net_value, big.net_quantity, len(big.days), big.last_day) == (
        Decimal(490000),
        5000,
        2,
        DAY,
    )
    assert [p.name for p in summary.sellers] == ["PROMOTER CO"]
    assert summary.sellers[0].kinds == {BLOCK}
    assert [p.name for p in summary.day_traders] == ["HFT LLP"]
    assert summarize_deals(deals, top=1).buyers == [big]


def test_insider_totals_count_market_trades_only():
    trades = parse_insider_trades(_rows(INSIDER_CSV))
    totals = insider_totals(trades)
    assert totals.promoter_bought == Decimal(500000) and totals.promoter_net == Decimal(500000)
    assert totals.others_sold == 0  # the director's sale has no value: counted, not summed
    assert (totals.on_market, totals.other_modes) == (2, 1)
