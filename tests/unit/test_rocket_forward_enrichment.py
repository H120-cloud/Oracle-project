from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd


BASE = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _bar(days: int, high: float, low: float, close: float):
    return {
        "timestamp": BASE + timedelta(days=days),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000,
    }


def _row(**overrides):
    row = {
        "row_id": "row-1",
        "ticker": "TEST",
        "alert_time": BASE.isoformat(),
        "price_at_alert": 10.0,
        "runner_tier": None,
        "mfe_1d": None,
        "mfe_2d": None,
        "mfe_5d": None,
        "mae_1d": None,
        "mae_2d": None,
        "mae_5d": None,
        "training_runner_tier": "UNKNOWN",
    }
    row.update(overrides)
    return row


class FakeProvider:
    def __init__(self, name, *, intraday=None, daily=None, error=None):
        self.name = name
        self.intraday = intraday or []
        self.daily = daily or []
        self.error = error
        self.calls = []

    def get_ohlcv(self, ticker, *, start, end, interval, prepost):
        self.calls.append((ticker, start, end, interval, prepost))
        if self.error:
            raise RuntimeError(self.error)
        return self.intraday if interval == "5m" else self.daily


def test_polygon_first_and_alpaca_fallback(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher

    polygon = FakeProvider("polygon", error="polygon unavailable")
    alpaca = FakeProvider(
        "alpaca",
        intraday=[_bar(0, 10.5, 9.8, 10.3), _bar(1, 11.0, 9.7, 10.8)],
        daily=[_bar(1, 11.0, 9.7, 10.8), _bar(2, 12.0, 9.5, 11.5), _bar(5, 12.5, 9.0, 12.0)],
    )
    enricher = RocketForwardEnricher(
        providers=[polygon, alpaca],
        state_dir=tmp_path,
        sleep_fn=lambda _: None,
    )

    result, summary = enricher.enrich(pd.DataFrame([_row()]))

    assert polygon.calls
    assert alpaca.calls
    assert result.loc[0, "forward_enrichment_provider"] == "alpaca"
    assert result.loc[0, "drawdown_data_quality"] == "intraday_exact"
    assert summary["provider_stats"]["polygon"]["failed_groups"] == 1
    assert summary["provider_stats"]["alpaca"]["successful_groups"] == 1


def test_durable_cache_avoids_repeat_provider_calls(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher

    provider = FakeProvider(
        "polygon",
        intraday=[_bar(0, 10.5, 9.8, 10.3)],
        daily=[_bar(1, 11.0, 9.7, 10.8), _bar(2, 12.0, 9.5, 11.5), _bar(5, 12.5, 9.0, 12.0)],
    )
    df = pd.DataFrame([_row()])

    first = RocketForwardEnricher(providers=[provider], state_dir=tmp_path, sleep_fn=lambda _: None)
    first.enrich(df)
    calls_after_first = len(provider.calls)

    second = RocketForwardEnricher(providers=[provider], state_dir=tmp_path, sleep_fn=lambda _: None)
    _, summary = second.enrich(df)

    assert calls_after_first > 0
    assert len(provider.calls) == calls_after_first
    assert summary["cache_hits"] == 1


def test_checkpoint_resume_skips_completed_group(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher

    provider = FakeProvider(
        "polygon",
        intraday=[_bar(0, 10.5, 9.8, 10.3)],
        daily=[_bar(1, 11.0, 9.7, 10.8), _bar(2, 12.0, 9.5, 11.5), _bar(5, 12.5, 9.0, 12.0)],
    )
    df = pd.DataFrame([_row()])

    first = RocketForwardEnricher(providers=[provider], state_dir=tmp_path, sleep_fn=lambda _: None)
    first.enrich(df)
    calls_after_first = len(provider.calls)

    resumed = RocketForwardEnricher(providers=[provider], state_dir=tmp_path, sleep_fn=lambda _: None)
    _, summary = resumed.enrich(df)

    assert len(provider.calls) == calls_after_first
    assert summary["checkpoint_skips"] == 1


def test_resume_refills_partial_cache_instead_of_skipping_it(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher

    intraday_only = FakeProvider(
        "polygon",
        intraday=[_bar(0, 10.5, 9.8, 10.3)],
    )
    df = pd.DataFrame([_row()])
    first = RocketForwardEnricher(
        providers=[intraday_only],
        state_dir=tmp_path,
        sleep_fn=lambda _: None,
    )
    first.enrich(df)

    daily_provider = FakeProvider(
        "polygon",
        daily=[_bar(1, 11.0, 9.7, 10.8), _bar(2, 12.0, 9.5, 11.5), _bar(5, 12.5, 9.0, 12.0)],
    )
    resumed = RocketForwardEnricher(
        providers=[daily_provider],
        state_dir=tmp_path,
        sleep_fn=lambda _: None,
    )
    result, summary = resumed.enrich(df)

    assert summary["cache_hits"] == 1
    assert daily_provider.calls
    assert result.loc[0, "mfe_5d"] == 25.0


def test_daily_proxy_reconstructs_exact_runner_label(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher

    provider = FakeProvider(
        "polygon",
        daily=[_bar(1, 11.0, 9.5, 10.8), _bar(2, 14.0, 9.0, 13.5), _bar(5, 15.0, 8.5, 14.0)],
    )
    enricher = RocketForwardEnricher(
        providers=[provider],
        state_dir=tmp_path,
        sleep_fn=lambda _: None,
    )

    result, _ = enricher.enrich(pd.DataFrame([_row()]))

    assert result.loc[0, "training_runner_tier"] == "MAJOR_RUNNER"
    assert result.loc[0, "drawdown_data_quality"] == "daily_proxy"
    assert result.loc[0, "mfe_1d"] == 10.0
    assert result.loc[0, "mfe_2d"] == 40.0


def test_provider_failure_is_logged(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher

    provider = FakeProvider("polygon", error="network down")
    enricher = RocketForwardEnricher(
        providers=[provider],
        state_dir=tmp_path,
        sleep_fn=lambda _: None,
        max_retries=2,
    )

    _, summary = enricher.enrich(pd.DataFrame([_row()]))

    failure_text = (tmp_path / "failures.jsonl").read_text(encoding="utf-8")
    assert "network down" in failure_text
    assert summary["failed_groups"] == 1


def test_smoke_selection_is_mixed_and_bounded():
    from src.core.agentic.rocket_forward_enrichment import select_smoke_rows

    rows = []
    for i in range(80):
        rows.append(
            _row(
                row_id=f"row-{i}",
                ticker=f"T{i % 12:02d}",
                alert_time=(BASE + timedelta(days=i)).isoformat(),
            )
        )
    selected = select_smoke_rows(pd.DataFrame(rows), limit=30)

    assert len(selected) == 30
    assert selected["ticker"].nunique() >= 10
    assert pd.to_datetime(selected["alert_time"]).dt.date.nunique() >= 20


def test_smoke_selection_preserves_source_indexes_for_v2_merge():
    from src.core.agentic.rocket_forward_enrichment import select_smoke_rows

    df = pd.DataFrame(
        [_row(row_id=f"row-{i}", ticker=f"T{i:02d}", alert_time=(BASE + timedelta(days=i)).isoformat()) for i in range(40)],
        index=range(100, 140),
    )

    selected = select_smoke_rows(df, limit=25)

    assert set(selected.index).issubset(set(df.index))
    assert min(selected.index) >= 100


def test_original_dataframe_is_not_mutated(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher

    provider = FakeProvider("polygon", daily=[_bar(1, 11.0, 9.5, 10.8)])
    df = pd.DataFrame([_row()])
    original = df.copy(deep=True)
    enricher = RocketForwardEnricher(
        providers=[provider],
        state_dir=tmp_path,
        sleep_fn=lambda _: None,
    )

    enricher.enrich(df)

    pd.testing.assert_frame_equal(df, original)


def test_synthetic_ticker_is_rejected_without_market_data_fetch(tmp_path):
    from src.core.agentic.rocket_forward_enrichment import RocketForwardEnricher
    from src.core.agentic.rocket_ticker_integrity import SYNTHETIC_REJECTION_REASON

    provider = FakeProvider("polygon", daily=[_bar(1, 11.0, 9.5, 10.8)])
    enricher = RocketForwardEnricher(
        providers=[provider],
        state_dir=tmp_path,
        sleep_fn=lambda _: None,
    )

    result, summary = enricher.enrich(pd.DataFrame([_row(ticker="GOOD001")]))

    assert provider.calls == []
    assert result.loc[0, "rejection_reason"] == SYNTHETIC_REJECTION_REASON
    assert summary["synthetic_rejected_rows"] == 1
