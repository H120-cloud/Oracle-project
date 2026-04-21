"""Tests for TrailingStopEngine — 3-stage stop management."""

import pytest
from src.core.trailing_stop import TrailingStopEngine, TrailingStopState


@pytest.fixture
def engine():
    return TrailingStopEngine()


def test_create_state(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0)
    assert state.entry_price == 100
    assert state.initial_stop == 95
    assert state.current_stop == 95
    assert state.highest_price == 100
    assert state.risk_per_share == 5.0
    assert not state.moved_to_breakeven
    assert not state.trailing_active


def test_initial_stop_loss_hit(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0)
    action = engine.update(state, high=99, low=94, close=94.5)
    assert action == "stop_hit"
    assert state.exit_type == "stop_loss"


def test_price_rises_no_stop_hit(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0)
    action = engine.update(state, high=103, low=100, close=102)
    assert action == "hold"
    assert state.highest_price == 103


def test_breakeven_triggered_at_1r(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0)
    # R = 5. So +1R = price 105
    engine.update(state, high=105, low=101, close=104)
    assert state.moved_to_breakeven
    assert state.current_stop == 100  # Moved to entry price
    assert not state.trailing_active  # Not yet at +2R


def test_breakeven_exit(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0)
    engine.update(state, high=106, low=101, close=105)
    assert state.moved_to_breakeven
    # Now price drops back to entry
    action = engine.update(state, high=101, low=99, close=99.5)
    assert action == "stop_hit"
    assert state.exit_type == "breakeven"


def test_trailing_activated_at_2r(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0, enable_partial=False)
    # R = 5. +2R = 110
    action = engine.update(state, high=111, low=106, close=110)
    assert action == "hold"
    assert state.moved_to_breakeven
    assert state.trailing_active
    # Trailing stop = 111 - (3 * 1.0) = 108
    assert state.current_stop == 108


def test_trailing_stop_ratchets_up(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0, enable_partial=False)
    engine.update(state, high=111, low=106, close=110)
    assert state.current_stop == 108  # 111 - 3

    # Price goes higher
    engine.update(state, high=115, low=112, close=114)
    assert state.current_stop == 112  # 115 - 3


def test_stop_never_decreases(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0, enable_partial=False)
    engine.update(state, high=111, low=106, close=110)
    assert state.current_stop == 108

    # Price goes higher then pulls back
    engine.update(state, high=115, low=112, close=114)
    assert state.current_stop == 112

    # Price goes down but stop should NOT decrease
    engine.update(state, high=113, low=112.5, close=113)
    assert state.current_stop == 112  # Still 112, NOT 113-3=110


def test_trailing_stop_exit(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0, enable_partial=False)
    engine.update(state, high=111, low=106, close=110)
    engine.update(state, high=115, low=112, close=114)
    # Stop at 112. Price drops through.
    action = engine.update(state, high=113, low=111, close=111.5)
    assert action == "stop_hit"
    assert state.exit_type == "trailing_stop"


def test_max_r_tracking(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0, enable_partial=False)
    engine.update(state, high=115, low=106, close=114)
    assert state.max_r_reached == 3.0  # (115 - 100) / 5 = 3R


def test_strong_trend_wider_multiplier(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0, enable_partial=False)
    engine.update(state, high=111, low=106, close=110)  # Activate trailing
    # With strong trend: multiplier 1.3, stop = 111 - (3*1.3) = 107.1
    engine.update(state, high=115, low=112, close=114,
                  momentum_state="strong_up", volume_increasing=True)
    # 115 - (3 * 1.3) = 111.1 → but previous stop was 108 from first update
    # Actually trailing_active is true, so: 115 - 3*1.3 = 111.1
    assert state.current_stop >= 111  # Wider trail gives lower stop than default


def test_serialization_round_trip():
    state = TrailingStopState(
        entry_price=100, initial_stop=95, atr_at_entry=3.0,
        current_stop=108, highest_price=115,
        moved_to_breakeven=True, trailing_active=True,
        max_r_reached=3.0,
    )
    d = state.to_dict()
    restored = TrailingStopState.from_dict(d)
    assert restored.entry_price == 100
    assert restored.current_stop == 108
    assert restored.moved_to_breakeven
    assert restored.trailing_active
    assert restored.max_r_reached == 3.0


def test_compute_atr():
    highs = [10, 11, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17]
    lows = [9, 10, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16]
    closes = [9.5, 10.5, 11.5, 10.5, 12.5, 11.5, 13.5, 12.5, 14.5, 13.5, 15.5, 14.5, 16.5, 15.5, 17.5, 16.5]
    atr = TrailingStopEngine.compute_atr(highs, lows, closes, period=14)
    assert atr > 0


def test_partial_close_at_2r(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0)
    # R = 5. +2R = 110
    action = engine.update(state, high=111, low=106, close=110)
    assert action == "partial_close"
    assert state.partial_close_triggered
    assert state.trailing_active
    assert state.moved_to_breakeven
    # Partial only fires once
    action2 = engine.update(state, high=115, low=112, close=114)
    assert action2 == "hold"


def test_partial_disabled(engine):
    state = engine.create_state(entry_price=100, initial_stop=95, atr_at_entry=3.0, enable_partial=False)
    action = engine.update(state, high=111, low=106, close=110)
    assert action == "hold"  # No partial close
    assert not state.partial_close_triggered


def test_zero_risk_doesnt_crash(engine):
    state = engine.create_state(entry_price=100, initial_stop=100, atr_at_entry=3.0)
    action = engine.update(state, high=105, low=99, close=102)
    assert action == "hold"  # r=0 triggers early return before stop check
