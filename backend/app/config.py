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
    # Alerts (M5). Telegram first; email is the backup when Telegram is not set up or a
    # send fails. Secrets only in .env, never in the repo.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Send research-only signals (strategies that failed spec section 6) one by one too,
    # clearly marked. Off: they are only listed in the daily summary.
    alert_research_signals: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    alert_email_from: str = ""
    alert_email_to: str = ""
    # News labels (M6). Keys live only in .env; without one the news brain is off.
    # news_provider: "claude" or "deepseek".
    news_provider: str = "claude"
    anthropic_api_key: str = ""
    news_model: str = "claude-opus-5-5"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    # Where the web app is, for links in alerts.
    web_url: str = "http://localhost:3000"

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def news_ready(self) -> bool:
        if self.news_provider == "deepseek":
            return bool(self.deepseek_api_key)
        return bool(self.anthropic_api_key)

    @property
    def email_ready(self) -> bool:
        return bool(self.smtp_host and self.alert_email_to)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
