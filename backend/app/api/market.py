"""The market mood: breadth, the engine's regime filter, mode and sector strength."""

from dataclasses import asdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.market.mood import ATTACK_BREADTH_PCT
from app.market.service import mood_on

router = APIRouter(prefix="/market", tags=["market"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/mood")
def mood(session: SessionDep, date: date | None = None) -> dict[str, Any]:
    """The mood on the newest completed scan, or on `date`'s. 404 when there is none."""
    found = mood_on(session, date)
    if found is None:
        raise HTTPException(
            404,
            f"No completed scan for {date}" if date else "No completed scan yet",
        )
    out = asdict(found)
    out["rule"] = (
        "defend: the regime filter is on (Nifty 50 below its 200-day EMA or India VIX in "
        "its top 10% of five years), risk per trade halved; attack: filter off, at least "
        f"{ATTACK_BREADTH_PCT:.0f}% of the scan universe above its 200-day EMA and more new "
        "52-week highs than lows; normal: anything else."
    )
    return out
