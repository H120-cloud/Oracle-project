import importlib
import sys
from pathlib import Path

from src.config import Settings


def test_alpaca_news_stream_disabled_as_source_by_default():
    # Alpaca was removed as a momentum news source (low-signal headlines). The
    # flag must default off so RSS polling is the source unless explicitly re-enabled.
    assert Settings(_env_file=None).alpaca_news_stream_enabled is False


def test_default_mode_preserves_legacy_systems_and_strategic_systems():
    settings = Settings(oracle_lean_mode=False, _env_file=None)
    status = settings.lean_mode_status()

    assert settings.oracle_lean_mode is False
    assert status["legacy_signals"] is True
    assert status["dip_bounce"] is True
    assert status["scanner_routes"] is True
    assert status["watchlist"] is True
    assert status["paper_trading"] is True
    assert status["backtest"] is True
    assert status["analysis_routes"] is True
    assert status["intelligence_routes"] is True
    assert status["htf_routes"] is True
    assert status["legacy_outcome_simulator"] is True
    assert status["news_momentum"] is True
    assert status["pre_news"] is True
    assert status["rocket_runner"] is True
    assert status["sec_intelligence"] is True
    assert status["telegram"] is True
    assert status["outcome_resolver"] is True
    assert status["learning_loops"] is True


def test_lean_mode_disables_legacy_systems_but_not_news_momentum_or_telegram():
    settings = Settings(oracle_lean_mode=True, _env_file=None)
    status = settings.lean_mode_status()

    assert status["legacy_signals"] is False
    assert status["dip_bounce"] is False
    assert status["scanner_routes"] is False
    assert status["watchlist"] is False
    assert status["paper_trading"] is False
    assert status["backtest"] is False
    assert status["analysis_routes"] is False
    assert status["intelligence_routes"] is False
    assert status["htf_routes"] is False
    assert status["legacy_outcome_simulator"] is False
    assert status["news_momentum"] is True
    assert status["pre_news"] is True
    assert status["rocket_runner"] is True
    assert status["sec_intelligence"] is True
    assert status["telegram"] is True
    assert status["market_data"] is True
    assert status["outcome_resolver"] is True
    assert status["learning_loops"] is True


def test_explicit_flag_overrides_lean_mode_default():
    settings = Settings(
        oracle_lean_mode=True,
        enable_watchlist=True,
        enable_legacy_signals=True,
        _env_file=None,
    )

    assert settings.watchlist_enabled is True
    assert settings.legacy_signals_enabled is True
    assert settings.paper_trading_system_enabled is False


def test_lean_mode_route_registration_keeps_strategic_routes(monkeypatch):
    import src.config as config

    monkeypatch.setattr(config, "get_settings", lambda: Settings(oracle_lean_mode=True, _env_file=None))

    import src.main as main

    main = importlib.reload(main)
    route_paths = {getattr(route, "path", "") for route in main.app.routes}

    assert "/api/v1/news-momentum/candidates" in route_paths
    assert "/api/v1/sec-intelligence/stats" in route_paths
    assert any(path.startswith("/api/v1/agentic") for path in route_paths)
    assert "/api/v1/signals/generate" not in route_paths
    assert "/api/v1/watchlist/" not in route_paths
    assert "/ws/signals" not in route_paths
    assert "/ws/watchlist" not in route_paths


def test_lean_mode_does_not_import_legacy_route_or_loop_modules(monkeypatch):
    import src.config as config

    legacy_modules = {
        "src.api.routes.scanner",
        "src.api.routes.signals",
        "src.api.routes.watchlist",
        "src.api.routes.models",
        "src.api.routes.analysis",
        "src.api.routes.backtest",
        "src.api.routes.intelligence",
        "src.api.routes.htf_scan",
        "src.api.routes.paper_trading",
        "src.core.outcome_simulator",
    }
    for module_name in legacy_modules | {"src.main"}:
        sys.modules.pop(module_name, None)

    monkeypatch.setattr(config, "get_settings", lambda: Settings(oracle_lean_mode=True, _env_file=None))

    import src.main as main

    main = importlib.reload(main)

    assert main.app is not None
    imported = legacy_modules & set(sys.modules)
    assert imported == set()


def test_frontend_lean_mode_does_not_static_import_legacy_pages():
    app_jsx = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
    legacy_static_imports = [
        "import Dashboard from './pages/Dashboard'",
        "import Analysis from './pages/Analysis'",
        "import Backtest from './pages/Backtest'",
        "import Performance from './pages/Performance'",
        "import Portfolio from './pages/Portfolio'",
        "import SettingsPage from './pages/Settings'",
        "import Watchlist from './pages/Watchlist'",
        "import Intelligence from './pages/Intelligence'",
        "import ActiveTrades from './pages/ActiveTrades'",
        "import PaperTrading from './pages/PaperTrading'",
    ]

    for import_line in legacy_static_imports:
        assert import_line not in app_jsx


def test_frontend_app_has_no_runtime_imports_for_archived_legacy_pages():
    app_jsx = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
    legacy_page_imports = [
        "import('./pages/Dashboard')",
        "import('./pages/Analysis')",
        "import('./pages/Backtest')",
        "import('./pages/Performance')",
        "import('./pages/Portfolio')",
        "import('./pages/Settings')",
        "import('./pages/Watchlist')",
        "import('./pages/Intelligence')",
        "import('./pages/ActiveTrades')",
        "import('./pages/PaperTrading')",
    ]

    for import_expr in legacy_page_imports:
        assert import_expr not in app_jsx


def test_lean_mode_telegram_command_handler_does_not_import_legacy_commands(monkeypatch):
    import src.config as config

    legacy_command_modules = {
        "src.core.volume_profile",
        "src.core.regime_detector",
        "src.core.stage_detector",
        "src.core.order_flow",
        "src.db.repositories",
    }
    for module_name in legacy_command_modules | {"src.services.telegram_command_handler"}:
        sys.modules.pop(module_name, None)

    monkeypatch.setattr(config, "get_settings", lambda: Settings(oracle_lean_mode=True, _env_file=None))

    import src.services.telegram_command_handler as handler

    handler = importlib.reload(handler)

    assert handler.LEGACY_TELEGRAM_COMMANDS_ENABLED is False
    assert legacy_command_modules & set(sys.modules) == set()


def test_phase4_legacy_routes_are_removed_from_runtime_tree():
    removed_routes = [
        "scanner.py",
        "signals.py",
        "watchlist.py",
        "models.py",
        "analysis.py",
        "backtest.py",
        "intelligence.py",
        "htf_scan.py",
        "paper_trading.py",
    ]

    runtime_routes = Path("src/api/routes")

    for route in removed_routes:
        assert not (runtime_routes / route).exists()


def test_phase4_legacy_archive_directory_is_deleted():
    assert not Path("archive/legacy").exists()


def test_phase4_legacy_model_trainer_is_removed():
    assert not Path("src/ml/trainer.py").exists()


def test_phase4_legacy_runtime_cluster_is_removed_from_runtime_tree():
    runtime_paths = [
        "src/api/dependencies.py",
        "src/services/signal_service.py",
        "src/services/watchlist_service.py",
        "src/services/logging_service.py",
        "src/ml/dip_model.py",
        "src/ml/bounce_model.py",
        "src/ml/feature_engineer.py",
        "src/ml/model_store.py",
        "src/core/dip_detector.py",
        "src/core/bounce_detector.py",
        "src/core/classifier.py",
        "src/core/backtester.py",
        "src/core/backtest_validator.py",
    ]

    for runtime_path in runtime_paths:
        assert not Path(runtime_path).exists()


def test_phase4_frontend_legacy_pages_are_removed_from_runtime_tree():
    legacy_pages = [
        "ActiveTrades.jsx",
        "Analysis.jsx",
        "Backtest.jsx",
        "Dashboard.jsx",
        "Intelligence.jsx",
        "PaperTrading.jsx",
        "Performance.jsx",
        "Portfolio.jsx",
        "Settings.jsx",
        "Watchlist.jsx",
    ]

    runtime_pages = Path("frontend/src/pages")

    for page in legacy_pages:
        assert not (runtime_pages / page).exists()
