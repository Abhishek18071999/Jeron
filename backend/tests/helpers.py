"""Small builders for test data."""

import io
import zipfile
from datetime import date
from decimal import Decimal

from app.data.provider import Bar

UDIFF_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)
LEGACY_HEADER = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,"
    "TOTALTRADES,ISIN,"
)
BC_HEADER = (
    "SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE"
)


def zipped(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def udiff_row(day: date, symbol: str, o, h, lo, c, prev, volume, series="EQ", isin="INE000000000"):
    return (
        f"{day},{day},CM,NSE,STK,1,{isin},{symbol},{series},,,,,{symbol} LTD,{o},{h},{lo},{c},"
        f"{c},{prev},,{c},,,{volume},{Decimal(str(c)) * volume},100,F1,1,,,,,"
    )


def udiff_zip(day: date, rows: list[str]) -> bytes:
    text = "\n".join([UDIFF_HEADER, *rows]) + "\n"
    return zipped(f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv", text)


def pr_zip(day: date, bc_rows: list[str]) -> bytes:
    return zipped(f"bc{day:%d%m%Y}.csv", "\n".join([BC_HEADER, *bc_rows]) + "\n")


def bar(symbol, day, o, h, lo, c, volume=1000, prev_close=None, series="EQ") -> Bar:
    return Bar(
        symbol,
        day,
        Decimal(str(o)),
        Decimal(str(h)),
        Decimal(str(lo)),
        Decimal(str(c)),
        volume,
        prev_close=None if prev_close is None else Decimal(str(prev_close)),
        series=series,
    )
