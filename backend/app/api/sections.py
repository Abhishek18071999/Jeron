"""The four sections (docs/plans/sections-v1.md): swing, intraday, positional and
long-term, each with its state, its strategies and what to buy."""

from dataclasses import asdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.sections.calc import SectionKey
from app.sections.service import SectionView, sections

router = APIRouter(prefix="/sections", tags=["sections"])
SessionDep = Annotated[Session, Depends(get_session)]


def _out(v: SectionView, detail: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": v.section.key.value,
        "name": v.section.name,
        "holding": v.section.holding,
        "about": v.section.about,
        "tier": None if v.section.tier is None else v.section.tier.value,
        "state": v.status.state.value,
        "headline": v.status.headline,
        "as_of": v.as_of,
        "max_positions": v.max_positions,
        "live_signals": len(v.live_signals),
        "research_signals": len(v.research_signals),
        "open_positions": len(v.positions),
        "strategies": [{**asdict(s), "tier": s.tier.value, "stage": s.stage} for s in v.strategies],
        "needs": v.needs,
    }
    if detail:
        out["signals"] = [asdict(c) for c in v.signals]
        out["positions"] = [asdict(p) for p in v.positions]
    return out


@router.get("")
def overview(session: SessionDep) -> list[dict[str, Any]]:
    """All four sections, newest scan day."""
    return [_out(v, detail=False) for v in sections(session)]


@router.get("/{key}")
def section(session: SessionDep, key: str, date: date | None = None) -> dict[str, Any]:
    """One section with its signal cards (of `date`, default the newest scan day) and
    open paper positions."""
    try:
        wanted = SectionKey(key)
    except ValueError:
        raise HTTPException(404, f"No section {key!r}") from None
    (view,) = sections(session, wanted, date)
    return _out(view, detail=True)
