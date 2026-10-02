from datetime import date
from decimal import Decimal

import pytest

from app.data.nse import index_closes_url, security_list_url
from app.data.nse_lists import (
    ListFormatError,
    parse_equity_list,
    parse_index_closes,
    parse_index_constituents,
    parse_security_list,
    parse_symbol_changes,
)
from app.scan.surveillance import read_asm_csv

# Rows copied from NSE's files.
INDEX_CLOSES = b"""Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield
Nifty 50,30-09-2026,22665,22809.35,22595.2,22620.45,-95.75,-.42,369406892,32476.02,19.36,2.78,1.22
Nifty 500,30-09-2026,22113.55,22229.2,22057.45,22072.1,-28.9,-.13,2713205059,92618.3,21.77,3.09,1.02
India VIX,30-09-2026,13.4125,13.8625,12.77,13.49,0.08,.58,-,-,-,-,-
"""  # noqa: E501
SEC_LIST = b"""Symbol,Series,Security Name,Band,Remarks
21STCENMGM,EQ,21ST CENTURY MANAGEMENT SERVICES LIMITED,2,"-"
AGSTRA,BZ,AGS TRANSACT TECHNOLOGIES LIMITED,2,"GSM STAGE - 0"
RELIANCE,EQ,RELIANCE INDUSTRIES LIMITED,No Band,"-"
OLDCO,BE,OLD COMPANY LIMITED,5,"GSM - Stage II"
SMEONE,SM,SME ONE LIMITED,5,"-"
"""
NIFTY500 = b"""Company Name,Industry,Symbol,Series,ISIN Code
360 ONE WAM Ltd.,Financial Services,360ONE,EQ,INE466L01038
ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022
"""
EQUITY_L = b"""SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
20MICRONS,20 Microns Limited,EQ,06-OCT-2008,5,1,INE144J01027,5
"""  # noqa: E501
SYMBOL_CHANGES = b"""Zydus Lifesciences Limited,CADILAHC,ZYDUSLIFE,07-MAR-2022
Some Company, Inc. Limited,OLDSYM,NEWSYM,01-JAN-2020
,780LTFL30,799LTFL30,19-FEB-2025
broken row
"""


def test_urls():
    assert index_closes_url(date(2026, 9, 30)).endswith(
        "/content/indices/ind_close_all_30092026.csv"
    )
    assert security_list_url(date(2020, 1, 1)).endswith("/content/equities/sec_list_01012020.csv")


def test_index_closes():
    rows = {r.index_name: r for r in parse_index_closes(INDEX_CLOSES, date(2026, 9, 30))}
    assert rows["Nifty 500"].close == Decimal("22072.1")
    assert rows["India VIX"].high == Decimal("13.8625")
    with pytest.raises(ListFormatError):
        parse_index_closes(INDEX_CLOSES, date(2026, 10, 1))
    with pytest.raises(ListFormatError):
        parse_index_closes(b"a,b\n1,2\n", date(2026, 9, 30))


def test_security_list_bands_and_gsm():
    rows = {r.symbol: r for r in parse_security_list(SEC_LIST)}
    assert set(rows) == {"21STCENMGM", "AGSTRA", "RELIANCE", "OLDCO"}  # no SME
    assert rows["21STCENMGM"].price_band == Decimal(2)
    assert rows["21STCENMGM"].gsm_stage is None and rows["21STCENMGM"].remarks is None
    assert rows["RELIANCE"].price_band is None
    assert rows["AGSTRA"].gsm_stage == "0"
    assert rows["OLDCO"].gsm_stage == "II"


def test_reference_lists():
    members = parse_index_constituents(NIFTY500)
    assert [(m.symbol, m.industry) for m in members] == [
        ("360ONE", "Financial Services"),
        ("ABB", "Capital Goods"),
    ]
    (equity,) = parse_equity_list(EQUITY_L)
    assert equity.name == "20 Microns Limited"
    assert equity.listing_date == date(2008, 10, 6)
    assert equity.isin == "INE144J01027"


def test_symbol_changes():
    changes = parse_symbol_changes(SYMBOL_CHANGES)
    assert [(c.old_symbol, c.new_symbol, c.change_date) for c in changes] == [
        ("CADILAHC", "ZYDUSLIFE", date(2022, 3, 7)),
        ("OLDSYM", "NEWSYM", date(2020, 1, 1)),
        ("780LTFL30", "799LTFL30", date(2025, 2, 19)),
    ]
    assert changes[1].company_name == "Some Company,Inc. Limited"
    assert changes[2].company_name is None


def test_asm_csv():
    content = (
        b"\xef\xbb\xbfSr No,Symbol,Security Name,ASM Stage\n1,abc,ABC Ltd,Stage I\n2,XYZ,XYZ Ltd,\n"
    )
    assert read_asm_csv(content) == {"ABC": "Stage I", "XYZ": None}
    with pytest.raises(ValueError):
        read_asm_csv(b"Name\nABC\n")
