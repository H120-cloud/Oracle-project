from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./oracle.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # App
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Market Data
    market_data_provider: str = "yfinance"

    # Scanner
    scanner_top_n: int = 20
    scanner_min_price: float = 1.00
    scanner_max_price: float = 500.00
    scanner_min_volume: int = 500_000

    # Signal
    signal_expiry_minutes: int = 30

    # V10: Alpaca API
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""

    # V10: Paper Trading
    paper_trading_enabled: bool = True
    paper_trading_use_alpaca: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
