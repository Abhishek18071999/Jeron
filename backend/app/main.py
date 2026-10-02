from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import backtests, data, health, scan
from app.config import get_settings

app = FastAPI(title="Jeron API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(data.router)
app.include_router(scan.router)
app.include_router(backtests.router)
