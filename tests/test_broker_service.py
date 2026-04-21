"""Tests for BrokerService — paper trading with trailing stops."""

import pytest
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.services.broker_service import BrokerService, PaperOrder, PaperPosition, ClosedTrade


@pytest.fixture
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="oracle_test_broker_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def broker(tmp_data_dir):
    return BrokerService(use_alpaca=False, data_dir=tmp_data_dir)


def _mock_signal(ticker="AAPL", entry=150.0, stop=145.0, targets=None, confidence=75, grade="B"):
    return SimpleNamespace(
        action=SimpleNamespace(value="BUY"),
        ticker=ticker,
        entry_price=entry,
        stop_price=stop,
        target_prices=targets or [160.0],
        confidence=confidence,
        setup_grade=grade,
        position_size_shares=10,
        htf_bias="BULLISH",
        atr_value=3.0,
    )


class TestOpenPosition:
    def test_open_creates_position_and_trailing_state(self, broker):
        order = PaperOrder(
            order_id="T-001", ticker="AAPL", side="buy", qty=10,
            order_type="market", stop_price=145.0, filled_price=150.0,
            filled_at="2024-01-01T10:00:00",
            created_at="2024-01-01T10:00:00",
            signal_confidence=75, signal_grade="B",
        )
        signal = SimpleNamespace(atr_value=3.0)
        broker._open_position(order, 145.0, [160.0], signal)

        assert "AAPL" in broker.positions
        assert "AAPL" in broker._trailing_states
        pos = broker.positions["AAPL"]
        assert pos.initial_stop == 145.0
        assert pos.atr_at_entry == 3.0
        ts = broker._trailing_states["AAPL"]
        assert ts.entry_price == 150.0
        assert ts.current_stop == 145.0


class TestUpdatePrices:
    def _setup_position(self, broker):
        order = PaperOrder(
            order_id="T-001", ticker="TEST", side="buy", qty=10,
            order_type="market", stop_price=95.0, filled_price=100.0,
            filled_at="2024-01-01T10:00:00",
            created_at="2024-01-01T10:00:00",
            signal_confidence=70, signal_grade="C",
        )
        signal = SimpleNamespace(atr_value=3.0)
        broker._open_position(order, 95.0, [115.0], signal)

    def test_price_update_modifies_position(self, broker):
        self._setup_position(broker)
        broker.update_prices({"TEST": 102.0})
        pos = broker.positions["TEST"]
        assert pos.current_price == 102.0
        assert pos.unrealized_pnl_pct > 0

    def test_stop_loss_closes_position(self, broker):
        self._setup_position(broker)
        broker.update_prices({"TEST": 93.0})
        assert "TEST" not in broker.positions
        assert len(broker.closed_trades) == 1
        assert broker.closed_trades[0].exit_reason == "stop_loss"

    def test_target_hit_closes_position(self, broker):
        self._setup_position(broker)
        # First push price up past target — this also triggers partial at +2R
        broker.update_prices({"TEST": 116.0})
        assert "TEST" not in broker.positions
        # Partial close trade + target close trade
        target_trades = [t for t in broker.closed_trades if t.exit_reason == "target"]
        assert len(target_trades) >= 1

    def test_breakeven_activation(self, broker):
        self._setup_position(broker)
        # R = 5. +1R = 105
        broker.update_prices({"TEST": 106.0})
        pos = broker.positions["TEST"]
        assert pos.moved_to_breakeven
        assert pos.stop_price == 100.0  # Moved to entry

    def test_trailing_activation(self, broker):
        self._setup_position(broker)
        # R = 5. +2R = 110. At +2R, partial close fires + trailing activates
        broker.update_prices({"TEST": 111.0})
        pos = broker.positions["TEST"]
        assert pos.trailing_active
        # Trail stop = 111 - 3 = 108
        assert pos.stop_price == 108.0
        # Partial close trade should have been created
        partial_trades = [t for t in broker.closed_trades if t.exit_reason == "partial_+2R"]
        assert len(partial_trades) == 1
        # Qty should have been halved (10 -> 5 partial, 5 remaining)
        assert pos.qty == 5


class TestClosePosition:
    def test_close_records_trade(self, broker):
        order = PaperOrder(
            order_id="T-001", ticker="AAPL", side="buy", qty=5,
            order_type="market", stop_price=145.0, filled_price=150.0,
            filled_at="2024-01-01T10:00:00",
            created_at="2024-01-01T10:00:00",
        )
        signal = SimpleNamespace(atr_value=3.0)
        broker._open_position(order, 145.0, [160.0], signal)

        trade = broker.close_position("AAPL", 155.0, "manual")
        assert trade is not None
        assert trade.pnl_pct > 0
        assert trade.exit_reason == "manual"
        assert "AAPL" not in broker.positions

    def test_close_nonexistent_returns_none(self, broker):
        assert broker.close_position("FAKE", 100.0) is None


class TestPersistence:
    def test_save_and_load_state(self, tmp_data_dir):
        broker1 = BrokerService(use_alpaca=False, data_dir=tmp_data_dir)
        order = PaperOrder(
            order_id="T-001", ticker="MSFT", side="buy", qty=10,
            order_type="market", stop_price=295.0, filled_price=300.0,
            filled_at="2024-01-01T10:00:00",
            created_at="2024-01-01T10:00:00",
            signal_confidence=80, signal_grade="A",
        )
        signal = SimpleNamespace(atr_value=4.0)
        broker1._open_position(order, 295.0, [315.0], signal)
        broker1._save_state()

        # Load into fresh broker
        broker2 = BrokerService(use_alpaca=False, data_dir=tmp_data_dir)
        assert "MSFT" in broker2.positions
        assert broker2.positions["MSFT"].entry_price == 300.0

    def test_trailing_states_persist(self, tmp_data_dir):
        broker1 = BrokerService(use_alpaca=False, data_dir=tmp_data_dir)
        order = PaperOrder(
            order_id="T-001", ticker="TSLA", side="buy", qty=5,
            order_type="market", stop_price=190.0, filled_price=200.0,
            filled_at="2024-01-01T10:00:00",
            created_at="2024-01-01T10:00:00",
        )
        signal = SimpleNamespace(atr_value=5.0)
        broker1._open_position(order, 190.0, [250.0], signal)  # High target so it won't close
        # Push to activate trailing (+2R = 220 with R=10)
        broker1.update_prices({"TSLA": 225.0})
        broker1._save_state()

        # Reload
        broker2 = BrokerService(use_alpaca=False, data_dir=tmp_data_dir)
        assert "TSLA" in broker2._trailing_states
        ts = broker2._trailing_states["TSLA"]
        assert ts.trailing_active
        assert ts.moved_to_breakeven
        assert ts.highest_price == 225.0


class TestPerformance:
    def test_empty_performance(self, broker):
        perf = broker.get_performance()
        assert perf["total_trades"] == 0

    def test_performance_with_trades(self, broker):
        for i, (entry, exit_p) in enumerate([(100, 110), (100, 95), (100, 108)]):
            order = PaperOrder(
                order_id=f"T-{i}", ticker=f"T{i}", side="buy", qty=10,
                order_type="market", stop_price=entry-5, filled_price=entry,
                filled_at="2024-01-01T10:00:00",
                created_at="2024-01-01T10:00:00",
            )
            signal = SimpleNamespace(atr_value=3.0)
            broker._open_position(order, entry-5, [entry+10], signal)
            broker.close_position(f"T{i}", exit_p, "test")

        perf = broker.get_performance()
        assert perf["total_trades"] == 3
        assert perf["winning_trades"] == 2
        assert perf["losing_trades"] == 1
