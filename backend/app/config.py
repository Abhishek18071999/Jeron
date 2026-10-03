"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="JERON_", extra="ignore")

    database_url: str = "postgresql+psycopg://jeron:jeron@localhost:5432/jeron"
    # Comma-separated origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:3000"
    timezone: str = "Asia/Kolkata"
    # Downloaded exchange files are kept here, unchanged, so history can be re-read.
    data_dir: str = "data"
    # Seconds between requests, to stay polite to NSE and Yahoo.
    nse_request_interval: float = 1.0
    yahoo_request_interval: float = 0.5
    # Risk manager (spec section 5). Paper accounts keep the values they opened with.
    capital: float = Field(default=1_000_000.0, gt=0)
    risk_pct: float = Field(default=1.0, ge=0.5, le=2.0)
    max_positions_swing: int = Field(default=5, ge=1)
    max_positions_positional: int = Field(default=8, ge=1)
    sector_cap_pct: float = Field(default=30.0, gt=0, le=100)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
