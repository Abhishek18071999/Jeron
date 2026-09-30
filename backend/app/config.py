"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
