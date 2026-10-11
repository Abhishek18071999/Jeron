"""The Settings page: risk and alert settings that can be changed without editing
`.env`, plus what is set up (no secrets) and the news labeller's spend this month."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.news.job import month_spend, month_start
from app.settings_store import EDITABLE, SettingsError, overrides, save_settings

router = APIRouter(tags=["settings"])
SessionDep = Annotated[Session, Depends(get_session)]


class SettingOut(BaseModel):
    key: str
    label: str
    help: str
    value: Any
    env_value: Any  # the `.env` value, used when the page has no change
    changed_at: datetime | None


class SetupOut(BaseModel):
    telegram: bool
    email: bool
    news_provider: str
    news_model: str
    news_ready: bool


class NewsSpendOut(BaseModel):
    since: datetime
    spent_usd: Decimal
    cap_usd: Decimal


class SettingsOut(BaseModel):
    settings: list[SettingOut]
    setup: SetupOut
    news_spend: NewsSpendOut


class SettingsIn(BaseModel):
    # key -> new value; null puts the `.env` value back.
    changes: dict[str, Any]


def _model(settings: Settings) -> str:
    return {
        "deepseek": settings.deepseek_model,
        "ollama": settings.ollama_model,
    }.get(settings.news_provider, settings.news_model)


def _view(session: Session) -> SettingsOut:
    env = get_settings()
    found = overrides(session)
    rows = []
    for key, meta in EDITABLE.items():
        o = found.get(key)
        rows.append(
            SettingOut(
                key=key,
                label=meta.label,
                help=meta.help,
                value=o.value if o else getattr(env, key),
                env_value=getattr(env, key),
                changed_at=o.changed_at if o else None,
            )
        )
    cap = found["news_monthly_budget_usd"].value if "news_monthly_budget_usd" in found else None
    return SettingsOut(
        settings=rows,
        setup=SetupOut(
            telegram=env.telegram_ready,
            email=env.email_ready,
            news_provider=env.news_provider,
            news_model=_model(env),
            news_ready=env.news_ready,
        ),
        news_spend=NewsSpendOut(
            since=month_start(),
            spent_usd=month_spend(session),
            cap_usd=Decimal(str(cap if cap is not None else env.news_monthly_budget_usd)),
        ),
    )


@router.get("/settings")
def get_settings_view(session: SessionDep) -> SettingsOut:
    return _view(session)


@router.put("/settings")
def put_settings(body: SettingsIn, session: SessionDep) -> SettingsOut:
    try:
        save_settings(session, body.changes)
    except SettingsError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _view(session)
