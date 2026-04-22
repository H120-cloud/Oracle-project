"""
Signal Service — V4 Orchestrator

Pipeline: Scanner → Volume Profile → Regime → Segmentation → Stage → Order Flow
→ Dip (± ML) → Bounce (± ML) → Classify → Decide (risk + stage + flow)
→ Rank → Log
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.config import get_settings
from src.core.scanner import MarketScanner
from src.core.finviz_scanner import FinvizScanner
from src.core.professional_scanner import ProfessionalScanner, to_scanned_stock
from src.core.discovery_engine import DiscoveryEngine
from src.core.dip_detector import DipDetector
from src.core.bounce_detector import BounceDetector
from src.core.classifier import StockClassifier
from src.core.decision_engine import DecisionEngine
from src.core.signal_ranker import SignalRanker
from src.core.volume_profile import VolumeProfileEngine
from src.core.regime_detector import RegimeDetector
from src.core.stock_segmenter import StockSegmenter
from src.core.stage_detector import StageDetector
from src.core.order_flow import OrderFlowAnalyzer
from src.core.ict_detector import ICTDetector
from src.core.bearish_detector import BearishDetector
from src.core.intelligence_engine import IntelligenceEngine
from src.core.htf_aware_scanner import HTFAwareScanner, HTFFilterMode, create_htf_aware_scanner
from src.ml.dip_model import DipModel
from src.ml.bounce_model import BounceModel
from src.ml.model_store import ModelStore
from src.models.schemas import (
    ScanFilter,
    ScannedStock,
    TradingSignal,
    SignalAction,
    SignalResponse,
    DipResult,
    DipFeatures,
    BounceResult,
    BounceFeatures,
    ICTFeatures,
    VolumeProfileData,
    RegimeData,
    MoveStage,
    OrderFlowData,
    BearishTransitionData,
    ExitWarningLevel,
    OHLCVBar,
)
from src.services.market_data import get_market_data_provider, DEFAULT_SCAN_UNIVERSE, IMarketDataProvider
from src.services.logging_service import LoggingService

logger = logging.getLogger(__name__)


class SignalService:
    """End-to-end pipeline: scan → analyze → decide → log."""

    def __init__(
        self,
        db: Optional[Session] = None,
        market_data: Optional[IMarketDataProvider] = None,
    ):
        settings = get_settings()
        # V10: Auto-select market data provider based on settings
        if market_data:
            self.market_data = market_data
        else:
            self.market_data = get_market_data_provider()
            logger.info(f"Using {self.market_data.__class__.__name__} for market data")
        self.scanner = MarketScanner(
            ScanFilter(
                min_price=settings.scanner_min_price,
                max_price=settings.scanner_max_price,
                min_volume=settings.scanner_min_volume,
                max_results=settings.scanner_top_n,
            )
        )
        self.dip_detector = DipDetector()
        self.bounce_detector = BounceDetector()
        self.classifier = StockClassifier()
        self.decision_engine = DecisionEngine(
            signal_expiry_minutes=settings.signal_expiry_minutes
        )
        self.signal_ranker = SignalRanker(top_n=5)

        # V2 ML models (cold-start safe — fall back to rule-based)
        model_store = ModelStore()
        self.dip_model = DipModel(model_store)
        self.bounce_model = BounceModel(model_store)

        # V3 advanced analysis
        self.volume_profile = VolumeProfileEngine()
        self.regime_detector = RegimeDetector()
        self.stock_segmenter = StockSegmenter()
        self.stage_detector = StageDetector()

        # V4 order flow
        self.order_flow = OrderFlowAnalyzer()

        # V4 ICT / Smart Money detection
        self.ict_detector = ICTDetector()

        # V6: Intelligence Engine for full analysis + auto-watchlist
        self.intelligence_engine = IntelligenceEngine(provider=self.market_data)

        self.logging_service = LoggingService(db) if db else None

    # ── Full pipeline ────────────────────────────────────────────────────

    def generate_signals(
        self,
        scan_type: str = "volume",
        watchlist: list[str] | None = None,
    ) -> SignalResponse:
        """Run the full scan → signal pipeline."""
        logger.info("Starting signal generation (scan_type=%s)", scan_type)

        # 1. Scan
        universe_df = self.market_data.get_scan_universe()
        if universe_df.empty:
            logger.warning("Empty scan universe")
            return SignalResponse(signals=[], generated_at=datetime.utcnow(), count=0)

        if watchlist:
            stocks = self.scanner.scan_watchlist(universe_df, watchlist)
        elif scan_type == "rvol":
            stocks = self.scanner.scan_top_rvol(universe_df)
        elif scan_type == "gainers":
            stocks = self.scanner.scan_top_gainers(universe_df)
        elif scan_type == "finviz":
            finviz_scanner = FinvizScanner(max_results=20)
            stocks = finviz_scanner.scan_gainers()
        elif scan_type == "finviz-under2":
            finviz_scanner = FinvizScanner(max_results=30)
            stocks = finviz_scanner.scan_under_2()
        elif scan_type == "professional":
            prof_scanner = ProfessionalScanner(max_results=15)
            tickers = DEFAULT_SCAN_UNIVERSE[:30]
            prof_stocks = prof_scanner.scan_universe(tickers)
            stocks = [to_scanned_stock(s) for s in prof_stocks]
        elif scan_type == "professional-discovery":
            logger.info("Starting professional-discovery scan...")
            engine = DiscoveryEngine(max_per_source=40, max_total=80)
            result = engine.discover(["finviz_gainers", "finviz_active", "finviz_unusual_volume", "news"])
            logger.info("Discovery found %d tickers: %s", len(result.tickers), result.tickers)
            
            if not result.tickers:
                logger.warning("No tickers discovered - using fallback universe")
                result.tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX", "AMD", "COIN"]
            
            prof_scanner = ProfessionalScanner(max_results=15)
            prof_stocks = prof_scanner.scan_universe(result.tickers)
            stocks = [to_scanned_stock(s) for s in prof_stocks]
            logger.info("Discovery scan: %d candidates -> %d results", len(result.tickers), len(stocks))
        elif scan_type == "professional-all":
            logger.info("Starting professional-all scan...")
            engine = DiscoveryEngine(max_per_source=30, max_total=120)
            result = engine.discover([
                "finviz_gainers", "finviz_active", "finviz_unusual_volume",
                "finviz_volatile", "finviz_penny", "news", "trending",
            ])
            logger.info("Discovery found %d tickers: %s", len(result.tickers), result.tickers)
            
            if not result.tickers:
                logger.warning("No tickers discovered - using fallback universe")
                result.tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "NFLX", "AMD", "COIN"]
            
            prof_scanner = ProfessionalScanner(max_results=20)
            prof_stocks = prof_scanner.scan_universe(result.tickers)
            stocks = [to_scanned_stock(s) for s in prof_stocks]
            logger.info("Full discovery scan: %d candidates -> %d results", len(result.tickers), len(stocks))
        elif scan_type == "professional-penny":
            logger.info("Starting professional-penny scan...")
            engine = DiscoveryEngine(max_per_source=40, max_total=60)
            result = engine.discover(["finviz_penny", "finviz_under5"])
            logger.info("Discovery found %d tickers: %s", len(result.tickers), result.tickers)
            
            if not result.tickers:
                logger.warning("No tickers discovered - using fallback penny stocks")
                result.tickers = ["SNDL", "CLOV", "WKHS", "NAKD", "TRCH", "XSPA", "CIDM", "NXTD", "DGLY", "ALF"]
            
            prof_scanner = ProfessionalScanner(max_results=15)
            prof_stocks = prof_scanner.scan_universe(result.tickers)
            stocks = [to_scanned_stock(s) for s in prof_stocks]
            logger.info("Penny discovery scan: %d candidates -> %d results", len(result.tickers), len(stocks))
        
        # V9: HTF-Aware Professional Scans
        elif scan_type == "htf-prefer-bullish":
            logger.info("Starting HTF-aware scan (prefer bullish)...")
            htf_scanner = create_htf_aware_scanner(
                lambda: ProfessionalScanner(max_results=20).scan_universe(DEFAULT_SCAN_UNIVERSE[:40]),
                self.market_data
            )
            htf_result = htf_scanner.scan(
                htf_filter_mode=HTFFilterMode.PREFER_BULLISH,
                max_results=15
            )
            stocks = htf_result.stocks
            logger.info(
                "HTF scan: %d candidates, %d blocked, %d boosted -> %d results",
                htf_result.total_candidates,
                htf_result.blocked_by_htf,
                htf_result.boosted_by_htf,
                len(stocks)
            )
        
        elif scan_type == "htf-only-bullish":
            logger.info("Starting HTF-aware scan (only bullish)...")
            htf_scanner = create_htf_aware_scanner(
                lambda: ProfessionalScanner(max_results=30).scan_universe(DEFAULT_SCAN_UNIVERSE[:50]),
                self.market_data
            )
            htf_result = htf_scanner.scan(
                htf_filter_mode=HTFFilterMode.ONLY_BULLISH,
                min_htf_strength=50.0,
                max_results=15
            )
            stocks = htf_result.stocks
            logger.info(
                "HTF scan: %d candidates, %d blocked, %d boosted -> %d results",
                htf_result.total_candidates,
                htf_result.blocked_by_htf,
                htf_result.boosted_by_htf,
                len(stocks)
            )
        
        elif scan_type == "htf-include-reversals":
            logger.info("Starting HTF-aware scan (include reversals)...")
            htf_scanner = create_htf_aware_scanner(
                lambda: ProfessionalScanner(max_results=25).scan_universe(DEFAULT_SCAN_UNIVERSE[:40]),
                self.market_data
            )
            htf_result = htf_scanner.scan(
                htf_filter_mode=HTFFilterMode.INCLUDE_REVERSALS,
                max_results=15
            )
            stocks = htf_result.stocks
            logger.info(
                "HTF scan: %d candidates, %d blocked, %d boosted -> %d results",
                htf_result.total_candidates,
                htf_result.blocked_by_htf,
                htf_result.boosted_by_htf,
                len(stocks)
            )
        
        else:
            stocks = self.scanner.scan_top_volume(universe_df)

        logger.info("Scanned %d stocks", len(stocks))

        # 2. Analyze each stock
        signals: list[TradingSignal] = []
        for stock in stocks:
            result = self._analyze_stock(stock)
            if result:
                signal, dip_feat, bounce_feat, ict_feat = result
                signals.append(signal)
                if self.logging_service:
                    try:
                        self.logging_service.log_signal(signal, dip_feat, bounce_feat, ict_feat)
                    except Exception as exc:
                        logger.error("Failed to log signal for %s: %s", stock.ticker, exc)

        # V2: Rank signals and return top setups
        ranked = self.signal_ranker.rank(signals)

        return SignalResponse(
            signals=ranked,
            generated_at=datetime.utcnow(),
            count=len(ranked),
        )

    # ── Single-stock analysis ────────────────────────────────────────────

    def analyze_single(self, ticker: str) -> Optional[TradingSignal]:
        """Analyze a single ticker through the full pipeline."""
        universe_df = self.market_data.get_scan_universe()
        row = universe_df[universe_df["ticker"] == ticker.upper()]
        if row.empty:
            logger.warning("Ticker %s not found in universe", ticker)
            return None

        r = row.iloc[0]
        stock = ScannedStock(
            ticker=r["ticker"],
            price=float(r["price"]),
            volume=float(r["volume"]),
            rvol=float(r["rvol"]) if r.get("rvol") is not None else None,
            change_percent=float(r["change_percent"]) if r.get("change_percent") is not None else None,
            scan_type="single",
        )

        result = self._analyze_stock(stock)
        if result is None:
            return None

        signal, dip_feat, bounce_feat, ict_feat = result
        if self.logging_service:
            try:
                self.logging_service.log_signal(signal, dip_feat, bounce_feat, ict_feat)
            except Exception as exc:
                logger.error("Failed to log signal for %s: %s", ticker, exc)

        return signal

    # ── Internal ─────────────────────────────────────────────────────────

    def _analyze_stock(
        self, stock: ScannedStock
    ) -> Optional[tuple[TradingSignal, Optional[DipFeatures], Optional[BounceFeatures], Optional[ICTFeatures]]]:
        """Full pipeline: V3 context → ICT → dip → bounce → classify → decide."""
        try:
            # V3: Fetch OHLCV bars once for all downstream engines
            bars = self.market_data.get_ohlcv(stock.ticker, period="1d", interval="1m")
            
            # V8: Fetch daily bars for HTF bias detection (need 60 days for 50+ daily bars)
            daily_bars: list[OHLCVBar] = []
            try:
                daily_bars = self.market_data.get_ohlcv(stock.ticker, period="3mo", interval="1d")
                logger.debug(f"[{stock.ticker}] Fetched {len(daily_bars)} daily bars for HTF analysis")
            except Exception as e:
                logger.warning(f"[{stock.ticker}] Failed to fetch daily bars for HTF: {e}")

            # V3: Volume Profile
            vol_profile: Optional[VolumeProfileData] = None
            if bars and len(bars) >= 10:
                vol_profile = self.volume_profile.compute(bars)

            # V3: Market Regime
            regime: Optional[RegimeData] = None
            if bars and len(bars) >= 30:
                regime = self.regime_detector.detect(bars)

            # V3: Stock Segmentation
            segment = self.stock_segmenter.classify(stock)

            # V3: Stage of Move
            stage_result = None
            if bars and len(bars) >= 30:
                stage_result = self.stage_detector.detect(stock.ticker, bars)

            # V4: ICT / Smart Money detection
            ict_features: Optional[ICTFeatures] = None
            if bars and len(bars) >= 10:
                ict_features = self.ict_detector.detect(stock.ticker, bars)

            # V3: Gate — only allow entries in Stage 1-2
            stage_blocked = (
                stage_result is not None and not stage_result.entry_allowed
            )

            # Dip features + rule-based detection
            dip_features = self.market_data.compute_dip_features(stock.ticker)
            dip_result: Optional[DipResult] = None
            if dip_features:
                dip_result = self.dip_detector.detect(stock.ticker, dip_features)
                # V2: Enhance with ML prediction
                ml_dip_prob = self.dip_model.predict(dip_features, dip_result.probability)
                dip_result.probability = ml_dip_prob

            # Bounce features + rule-based detection
            bounce_features, current_price = self.market_data.compute_bounce_features(
                stock.ticker
            )
            bounce_result: Optional[BounceResult] = None
            if bounce_features:
                bounce_result = self.bounce_detector.detect(
                    stock.ticker, bounce_features, current_price or stock.price
                )
                # V2: Enhance with ML prediction
                ml_bounce_prob = self.bounce_model.predict(
                    bounce_features, bounce_result.probability
                )
                bounce_result.probability = ml_bounce_prob

            # Classify
            classification = self.classifier.classify(
                dip=dip_result,
                bounce=bounce_result,
                change_percent=stock.change_percent,
                volume=stock.volume,
            )

            # V4: Order Flow detection
            flow: Optional[OrderFlowData] = None
            if bars and len(bars) >= 5:
                flow = self.order_flow.analyze(stock.ticker, bars)

            # V3: Decide with ICT precision context
            # V8: Pass daily_bars for HTF bias detection
            signal = self.decision_engine.decide(
                stock=stock,
                classification=classification,
                dip=dip_result,
                bounce=bounce_result,
                ict=ict_features,
                vol_profile=vol_profile,
                bars=bars,
                daily_bars=daily_bars,
            )

            # V3: Attach additional metadata to signal
            signal.order_flow = flow
            signal.regime = regime.regime.value if regime else None
            signal.stock_type = segment.stock_type.value
            if stage_result:
                signal.stage = stage_result.stage.value

            # V4: Order flow gate — downgrade BUY to WATCH if bearish flow
            if flow and flow.signal == "bearish" and signal.action == SignalAction.BUY:
                signal.action = SignalAction.WATCH
                signal.reason = (signal.reason or []) + [
                    f"Downgraded: bearish order flow (imb={flow.bid_ask_imbalance:.2f})"
                ]

            # V3: Stage gate — downgrade BUY to WATCH if stage 3-5
            if stage_blocked and signal.action == SignalAction.BUY:
                signal.action = SignalAction.WATCH
                signal.reason = (signal.reason or []) + [
                    f"Downgraded: stage {stage_result.stage.value} ({stage_result.reason})"
                ]

            # V3: Regime sensitivity adjustment on reason
            if regime and regime.sensitivity_multiplier != 1.0:
                signal.reason = (signal.reason or []) + [
                    f"Regime: {regime.regime.value} (sens={regime.sensitivity_multiplier:.1f}x)"
                ]

            # V6: Bearish transition / exit warning detection
            bearish_result = None
            try:
                bearish_detector = BearishDetector()
                bearish_result = bearish_detector.detect(stock.ticker, bars, volume_profile)
                
                if bearish_result:
                    # Add bearish data to signal for downstream use
                    signal.bearish_state = bearish_result.bearish_state.value
                    signal.bearish_probability = bearish_result.bearish_probability
                    signal.exit_warning = bearish_result.exit_warning.value != "none"
                    signal.key_support_level = bearish_result.key_support_level
                    signal.invalidation_level = bearish_result.invalidation_level
                    signal.top_bearish_reasons = bearish_result.top_reasons
                    
                    # Downgrade or block signals based on bearish state
                    if bearish_result.exit_warning == ExitWarningLevel.EXIT_SIGNAL:
                        if signal.action == SignalAction.BUY:
                            signal.action = SignalAction.NO_ACTION
                            signal.reason = (signal.reason or []) + [
                                f"BLOCKED: Confirmed bearish state (prob={bearish_result.bearish_probability:.0f}%)"
                            ]
                        signal.risk_score = max(signal.risk_score, 8)
                    elif bearish_result.exit_warning == ExitWarningLevel.STRONG_WARNING:
                        if signal.action == SignalAction.BUY:
                            signal.action = SignalAction.WATCH
                            signal.reason = (signal.reason or []) + [
                                f"Downgraded: Strong bearish warning (prob={bearish_result.bearish_probability:.0f}%)"
                            ]
                        signal.risk_score = max(signal.risk_score, 6)
                    elif bearish_result.exit_warning == ExitWarningLevel.EARLY_WARNING:
                        if signal.action == SignalAction.BUY and bearish_result.bearish_probability > 40:
                            signal.risk_score = max(signal.risk_score, 5)
                            signal.reason = (signal.reason or []) + [
                                f"Caution: Early bearish signs (prob={bearish_result.bearish_probability:.0f}%)"
                            ]
            except Exception as exc:
                logger.warning("Bearish detection failed for %s: %s", stock.ticker, exc)

            # V3: Enhanced ICT logging
            ict_status = "-"
            if ict_features:
                if ict_features.trap_detected:
                    ict_status = "TRAP"
                elif ict_features.structure_break_confirmed:
                    ict_status = f"MSB@{ict_features.micro_high_level:.2f}"
                elif ict_features.liquidity_sweep:
                    ict_status = f"sweep@{ict_features.sweep_level:.2f}"
                elif ict_features.is_overextended:
                    ict_status = f"ext{ict_features.extension_pct:.0f}%"

            logger.info(
                "Signal [%s]: action=%s class=%s risk=%s grade=%s conf=%s ict_score=%s ict=%s",
                stock.ticker, signal.action.value, signal.classification.value,
                signal.risk_score, signal.setup_grade, signal.confidence,
                ict_features.ict_score if ict_features else "-",
                ict_status,
            )
            return signal, dip_features, bounce_features, ict_features

        except Exception as exc:
            logger.error("Analysis failed for %s: %s", stock.ticker, exc, exc_info=True)
            return None
