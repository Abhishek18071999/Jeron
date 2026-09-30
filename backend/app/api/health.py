from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter()


class Health(BaseModel):
    status: str
    database: str


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> Health:
    try:
        session.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        database = "unreachable"
    return Health(status="ok" if database == "ok" else "degraded", database=database)
