"""
Unit tests for the back-fill driver.

Covers:
  - MFE/MAE computation math
  - Outcome classification thresholds
  - Checkpoint persistence
  - Grouping logic
  - End-to-end driver run with a mocked provider
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.agentic.news_momentum_backfill import (
    BackfillDriver,
    BackfillError,
    _GroupKey,
    _alert_time_from_record,
    _classify_outcome,
    _compute_mfe_mae,
    _price_at_alert_from_record,
    _record_id_from_record,
)
from src.core.agentic.news_momentum_models import (
    AlertOutcome,
    NewsMomentumCandidate,
    TelegramAlertRecord,
)

pytestmark = [pytest.mark.unit]


class TestPureFunctions:
    def test_compute_mfe_mae_basic(self):
        mfe, mae = _compute_mfe_mae(
            price_at_alert=10.0,
            price_15m=11.0,
            price_1h=12.0,
            price_4h=10.5,
            next_day_high=13.0,
            two_day_high=14.0,
            five_day_high=15.0,
            next_day_close=9.5,
        )
        # max high = 15.0 → mfe = (15-10)/10 * 100 = 50.0
        assert mfe == 50.0
        # min low = 9.5 → mae = (10-9.5)/10 * 100 = 5.0
        assert mae == 5.0

    def test_compute_mfe_mae_no_highs(self):
        mfe, mae = _compute_mfe_mae(
            price_at_alert=10.0,
            price_15m=None,
            price_1h=None,
            price_4h=None,
            next_day_high=None,
            two_day_high=None,
            five_day_high=None,
            next_day_close=9.0,
        )
        assert mfe is None
        assert mae == 10.0

    def test_compute_mfe_mae_invalid_price(self):
        mfe, mae = _compute_mfe_mae(
            price_at_alert=0.0,
            price_15m=11.0,
            price_1h=None,
            price_4h=None,
            next_day_high=None,
            two_day_high=None,
            five_day_high=None,
            next_day_close=None,
        )
        assert mfe is None
        assert mae is None

    def test_classify_great(self):
        assert _classify_outcome(mfe_pct=30.0, mae_pct=5.0) == AlertOutcome.GREAT_ALERT.value

    def test_classify_good(self):
        assert _classify_outcome(mfe_pct=15.0, mae_pct=5.0) == AlertOutcome.GOOD_ALERT.value

    def test_classify_no_follow_through(self):
        assert _classify_outcome(mfe_pct=1.0, mae_pct=1.0) == AlertOutcome.NO_FOLLOW_THROUGH.value

    def test_classify_trap_low_mfe_high_mae(self):
        assert _classify_outcome(mfe_pct=1.5, mae_pct=10.0) == AlertOutcome.TRAP_ALERT.value

    def test_classify_trap_high_mae(self):
        assert _classify_outcome(mfe_pct=5.0, mae_pct=20.0) == AlertOutcome.TRAP_ALERT.value

    def test_classify_late(self):
        assert _classify_outcome(mfe_pct=5.0, mae_pct=5.0) == AlertOutcome.LATE_ALERT.value


class TestRecordHelpers:
    def test_alert_time_telegram(self):
        dt = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        rec = TelegramAlertRecord(
            alert_id="A", ticker="X", sent_at=dt,
            catalyst_type="other", session_type="premarket",
            price_at_alert=1.0, news_impact_score=50.0,
            expected_return_score=50.0, continuation_probability=50.0,
            multi_day_score=0.0,
        )
        assert _alert_time_from_record(rec) == dt

    def test_alert_time_candidate(self):
        dt = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        rec = NewsMomentumCandidate(
            ticker="X", headline="H", source="finviz",
            published_at=dt, session="premarket",
            catalyst_category="corporate", catalyst_sub_type="other",
        )
        assert _alert_time_from_record(rec) == dt

    def test_price_at_alert_telegram(self):
        rec = TelegramAlertRecord(
            alert_id="A", ticker="X", sent_at=datetime.now(timezone.utc),
            catalyst_type="other", session_type="premarket",
            price_at_alert=2.5, news_impact_score=50.0,
            expected_return_score=50.0, continuation_probability=50.0,
            multi_day_score=0.0,
        )
        assert _price_at_alert_from_record(rec) == 2.5

    def test_price_at_alert_candidate(self):
        rec = NewsMomentumCandidate(
            ticker="X", headline="H", source="finviz",
            published_at=datetime.now(timezone.utc), session="premarket",
            catalyst_category="corporate", catalyst_sub_type="other",
            current_price=3.0,
        )
        assert _price_at_alert_from_record(rec) == 3.0

    def test_record_id_telegram(self):
        rec = TelegramAlertRecord(
            alert_id="shadow_123", ticker="X", sent_at=datetime.now(timezone.utc),
            catalyst_type="other", session_type="premarket",
            price_at_alert=1.0, news_impact_score=50.0,
            expected_return_score=50.0, continuation_probability=50.0,
            multi_day_score=0.0,
        )
        assert _record_id_from_record(rec) == "shadow_123"


class TestGrouping:
    def test_group_records_by_ticker_date(self):
        dt = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
        records = [
            TelegramAlertRecord(
                alert_id=f"A{i}", ticker="AAPL" if i % 2 == 0 else "TSLA",
                sent_at=dt + timedelta(hours=i),
                catalyst_type="other", session_type="premarket",
                price_at_alert=1.0, news_impact_score=50.0,
                expected_return_score=50.0, continuation_probability=50.0,
                multi_day_score=0.0,
            )
            for i in range(4)
        ]
        groups = BackfillDriver._group_records(records)
        # All on same date, so two groups (AAPL, TSLA)
        assert len(groups) == 2
        assert len(groups[_GroupKey("AAPL", "2026-05-27")]) == 2
        assert len(groups[_GroupKey("TSLA", "2026-05-27")]) == 2


class TestCheckpointing:
    def test_save_and_load_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run_1"
            driver = BackfillDriver(run_id="run_1", output_dir=out, politeness_seconds=0)
            driver.completed_groups = {"AAPL|2026-05-27"}
            driver.failed_groups = {"TSLA|2026-05-27": "no_data"}
            driver.stats = {"total_groups": 10, "completed": 1, "failed": 1, "shadow_resolved": 5, "candidate_resolved": 3}
            driver._save_checkpoint()

            # Fresh instance should pick up checkpoint
            driver2 = BackfillDriver(run_id="run_1", output_dir=out, politeness_seconds=0)
            assert "AAPL|2026-05-27" in driver2.completed_groups
            assert driver2.failed_groups["TSLA|2026-05-27"] == "no_data"
            assert driver2.stats["shadow_resolved"] == 5


class TestEndToEndWithMockProvider:
    def test_resolve_group_with_mock_bars(self, tmp_path):
        """Run a single group through the driver with a mocked provider."""
        mock_provider = MagicMock()
        # Intraday bars: 5m bars from 10:00 to 14:00
        base = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
        intraday = []
        for i in range(48):  # 4 hours * 12 bars/hour
            ts = base + timedelta(minutes=5 * i)
            close = 10.0 + i * 0.1  # steadily rising
            intraday.append(MagicMock(
                timestamp=ts,
                open=close - 0.05,
                high=close + 0.05,
                low=close - 0.05,
                close=close,
                volume=1000,
            ))

        # Daily bars: next day high is 15.0, close is 12.0
        daily = [
            MagicMock(
                timestamp=datetime(2026, 5, 27, tzinfo=timezone.utc),
                open=10.0, high=10.5, low=9.9, close=10.2, volume=1000,
            ),
            MagicMock(
                timestamp=datetime(2026, 5, 28, tzinfo=timezone.utc),
                open=10.3, high=15.0, low=10.0, close=12.0, volume=1000,
            ),
        ]

        mock_provider.get_ohlcv.side_effect = lambda *args, **kwargs: (
            intraday if kwargs.get("interval") == "5m" else daily
        )

        out = tmp_path / "run_test"
        driver = BackfillDriver(run_id="run_test", output_dir=out, politeness_seconds=0)

        # Create a minimal shadow record
        alert_time = base
        rec = TelegramAlertRecord(
            alert_id="shadow_AAPL_test",
            ticker="AAPL",
            sent_at=alert_time,
            catalyst_type="other",
            session_type="premarket",
            price_at_alert=10.0,
            news_impact_score=50.0,
            expected_return_score=50.0,
            continuation_probability=50.0,
            multi_day_score=0.0,
        )
        key = _GroupKey("AAPL", "2026-05-27")

        resolved = driver._resolve_group(key, [rec], mock_provider)

        assert len(resolved) == 1
        r = resolved[0]
        assert r.record_id == "shadow_AAPL_test"
        assert r.mfe_pct is not None
        assert r.mfe_pct > 0
        assert r.outcome is not None
        assert r.price_15m_later is not None
        assert r.price_1h_later is not None

        # Sidecar should have been written
        assert driver.shadow_sidecar.exists()
        lines = driver.shadow_sidecar.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["record_id"] == "shadow_AAPL_test"
        assert payload["mfe_pct"] == r.mfe_pct

    def test_driver_skips_completed_groups(self, tmp_path):
        mock_provider = MagicMock()
        out = tmp_path / "run_skip"
        driver = BackfillDriver(run_id="run_skip", output_dir=out, politeness_seconds=0)
        driver.completed_groups = {"AAPL|2026-05-27"}
        driver.stats["total_groups"] = 1

        # If we call run() with a group that's already completed, provider should not be called
        with patch.object(driver, "load_shadow", return_value=[]):
            with patch.object(driver, "load_candidates", return_value=[]):
                result = driver.run()

        assert result["completed"] == 1
        assert result["shadow_resolved"] == 0
        mock_provider.get_ohlcv.assert_not_called()

    def test_driver_raises_when_no_bars_returned(self, tmp_path):
        """When provider returns no bars, group fails with a clear BackfillError."""
        mock_provider = MagicMock()
        mock_provider.get_ohlcv.return_value = []

        out = tmp_path / "run_err"
        driver = BackfillDriver(run_id="run_err", output_dir=out, politeness_seconds=0)

        rec = TelegramAlertRecord(
            alert_id="shadow_TSLA_test",
            ticker="TSLA",
            sent_at=datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc),
            catalyst_type="other",
            session_type="premarket",
            price_at_alert=10.0,
            news_impact_score=50.0,
            expected_return_score=50.0,
            continuation_probability=50.0,
            multi_day_score=0.0,
        )

        key = _GroupKey("TSLA", "2026-05-27")
        with pytest.raises(BackfillError, match="No bars returned"):
            driver._resolve_group(key, [rec], mock_provider)
