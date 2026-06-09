"""Delivery-integrity tests for the Telegram outbox.

Covers the bugs that could silently drop or mishandle approved alerts:
- lost-update race (a new alert enqueued during a drain's send must survive)
- permanent 4xx errors dead-letter immediately instead of burning 6 retries
- 429 stays retryable
- old sent/dead records are pruned so the file doesn't grow unbounded
"""

import asyncio
from datetime import timedelta

import pytest

from src.services import telegram_outbox as ob


@pytest.mark.unit
def test_drain_preserves_alert_enqueued_during_send(tmp_path):
    path = tmp_path / "outbox.jsonl"
    ob.enqueue_alert(alert_id="A", message="alert A", retry_after=0, path=path)

    async def send_func(_msg):
        # A different alert fails and is enqueued WHILE this send is awaiting.
        ob.enqueue_alert(alert_id="B", message="alert B", retry_after=0, path=path)
        return ob.OutboxSendResult(success=True)

    asyncio.run(ob.drain_pending(send_func, path=path))

    ids = {r.alert_id: r for r in ob.load_outbox(path)}
    assert ids["A"].status == "sent"
    assert "B" in ids, "alert enqueued during the drain was clobbered (lost update)"


@pytest.mark.unit
def test_permanent_error_dead_letters_immediately(tmp_path):
    path = tmp_path / "outbox.jsonl"
    ob.enqueue_alert(alert_id="X", message="x", retry_after=0, path=path)

    async def send_func(_msg):
        return ob.OutboxSendResult(success=False, error="telegram_api_400")

    stats = asyncio.run(ob.drain_pending(send_func, path=path))

    assert stats["dead_letter"] == 1
    rec = {r.alert_id: r for r in ob.load_outbox(path)}["X"]
    assert rec.status == "dead_letter"
    assert rec.attempts == 1, "permanent 4xx should not burn all retry attempts"


@pytest.mark.unit
def test_rate_limit_429_stays_retryable(tmp_path):
    path = tmp_path / "outbox.jsonl"
    ob.enqueue_alert(alert_id="Y", message="y", retry_after=0, path=path)

    async def send_func(_msg):
        return ob.OutboxSendResult(success=False, error="telegram_api_429", retry_after=1)

    stats = asyncio.run(ob.drain_pending(send_func, path=path))

    assert stats["failed"] == 1
    rec = {r.alert_id: r for r in ob.load_outbox(path)}["Y"]
    assert rec.status == "failed", "429 is retryable and must not dead-letter"


@pytest.mark.unit
def test_truncate_for_telegram_caps_length():
    from src.services.telegram_service import _truncate_for_telegram, TELEGRAM_MAX_LEN

    assert _truncate_for_telegram("hello") == "hello"
    out = _truncate_for_telegram("x" * 5000)
    assert len(out) <= TELEGRAM_MAX_LEN
    assert out.endswith("(truncated)")


@pytest.mark.unit
def test_old_sent_records_are_pruned(tmp_path):
    path = tmp_path / "outbox.jsonl"
    old = ob.TelegramOutboxRecord(
        alert_id="OLD", status="sent", created_at=ob._now() - timedelta(days=365)
    )
    ob.save_outbox([old], path)
    ob.enqueue_alert(alert_id="NEW", message="n", retry_after=0, path=path)

    async def send_func(_msg):
        return ob.OutboxSendResult(success=True)

    asyncio.run(ob.drain_pending(send_func, path=path))

    ids = {r.alert_id for r in ob.load_outbox(path)}
    assert "OLD" not in ids, "stale sent record should be pruned"
    assert "NEW" in ids
