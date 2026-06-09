from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


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
    oracle_frontend_auth_enabled: bool = True

    # Market Data
    market_data_provider: str = "yfinance"

    # Scanner
    scanner_top_n: int = 20
    scanner_min_price: float = 1.00
    scanner_max_price: float = 500.00
    scanner_min_volume: int = 500_000

    # Signal
    signal_expiry_minutes: int = 30

    # V10: AlphaVantage API
    alphavantage_api_key: str = ""

    # Polygon.io (historical news backfill)
    polygon_api_key: str = ""

    # V10: Alpaca API
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_data_feed: str = "iex"
    # Real-time Alpaca news stream as a momentum source — disabled. Its headlines
    # were overwhelmingly low-signal (almost all blocked on impact_floor /
    # bad_ticker / no_price). RSS polling (Finviz / StockTitan / PRNewswire /
    # etc.) remains the news source. This flag does NOT affect Alpaca market-data
    # or paper trading. Set ALPACA_NEWS_STREAM_ENABLED=true to re-enable.
    alpaca_news_stream_enabled: bool = False

    # V10: Paper Trading
    paper_trading_enabled: bool = True
    paper_trading_use_alpaca: bool = False
    paper_trading_data_dir: str = "./data/paper_trading"

    # Telegram Alerts
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Oracle Lean Mode
    oracle_lean_mode: bool = False
    enable_legacy_signals: Optional[bool] = None
    enable_dip_bounce: Optional[bool] = None
    enable_scanner_routes: Optional[bool] = None
    enable_watchlist: Optional[bool] = None
    enable_paper_trading: Optional[bool] = None
    enable_backtest: Optional[bool] = None
    enable_analysis_routes: Optional[bool] = None
    enable_intelligence_routes: Optional[bool] = None
    enable_htf_routes: Optional[bool] = None
    enable_legacy_outcome_simulator: Optional[bool] = None

    def _legacy_enabled(self, value: Optional[bool]) -> bool:
        if value is not None:
            return value
        return not self.oracle_lean_mode

    @property
    def legacy_signals_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_legacy_signals)

    @property
    def dip_bounce_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_dip_bounce)

    @property
    def scanner_routes_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_scanner_routes)

    @property
    def watchlist_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_watchlist)

    @property
    def paper_trading_system_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_paper_trading)

    @property
    def backtest_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_backtest)

    @property
    def analysis_routes_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_analysis_routes)

    @property
    def intelligence_routes_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_intelligence_routes)

    @property
    def htf_routes_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_htf_routes)

    @property
    def legacy_outcome_simulator_enabled(self) -> bool:
        return self._legacy_enabled(self.enable_legacy_outcome_simulator)

    def lean_mode_status(self) -> dict[str, bool]:
        return {
            "legacy_signals": self.legacy_signals_enabled,
            "dip_bounce": self.dip_bounce_enabled,
            "scanner_routes": self.scanner_routes_enabled,
            "watchlist": self.watchlist_enabled,
            "paper_trading": self.paper_trading_system_enabled,
            "backtest": self.backtest_enabled,
            "analysis_routes": self.analysis_routes_enabled,
            "intelligence_routes": self.intelligence_routes_enabled,
            "htf_routes": self.htf_routes_enabled,
            "legacy_outcome_simulator": self.legacy_outcome_simulator_enabled,
            "news_momentum": True,
            "pre_news": True,
            "rocket_runner": True,
            "sec_intelligence": True,
            "telegram": True,
            "market_data": True,
            "outcome_resolver": True,
            "learning_loops": True,
        }

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
