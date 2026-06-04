from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services import telegram_outbox
from src.services.telegram_outbox import (
    OutboxSendResult,
    TelegramOutboxRecord,
    drain_pending,
    enqueue_alert,
    load_outbox,
    save_outbox,
)


def _ready(records, path):
    for record in records:
        record.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    save_outbox(records, path=path)


def test_duplicate_alert_id_is_not_duplicated(tmp_path):
    path = tmp_path / "telegram_outbox.jsonl"

    enqueue_alert(alert_id="same-id", message="first", ticker="AAA", path=path)
    enqueue_alert(alert_id="same-id", message="second", ticker="BBB", path=path)

    records = load_outbox(path=path)
    assert len(records) == 1
    assert records[0].alert_id == "same-id"
    assert records[0].message == "second"


@pytest.mark.asyncio
async def test_timeout_failure_is_retried_then_sent(tmp_path):
    path = tmp_path / "telegram_outbox.jsonl"
    enqueue_alert(alert_id="retry-id", message="hello", path=path, retry_after=0)
    _ready(load_outbox(path=path), path)

    async def fail_once(_message):
        return OutboxSendResult(False, error="timeout")

    stats = await drain_pending(fail_once, path=path)
    assert stats["failed"] == 1

    records = load_outbox(path=path)
    assert records[0].status == "failed"
    assert records[0].attempts == 1

    _ready(records, path)

    async def succeed(_message):
        return OutboxSendResult(True, response={"ok": True})

    stats = await drain_pending(succeed, path=path)
    records = load_outbox(path=path)

    assert stats["sent"] == 1
    assert records[0].status == "sent"
    assert records[0].telegram_response == {"ok": True}


@pytest.mark.asyncio
async def test_telegram_429_retry_after_is_respected(tmp_path):
    path = tmp_path / "telegram_outbox.jsonl"
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    record = TelegramOutboxRecord(
        alert_id="rate-limit",
        message="hello",
        next_retry_at=now - timedelta(seconds=1),
    )
    save_outbox([record], path=path)

    async def rate_limited(_message):
        return OutboxSendResult(False, error="telegram_api_429", retry_after=42)

    stats = await drain_pending(rate_limited, now=now, path=path)
    records = load_outbox(path=path)

    assert stats["failed"] == 1
    assert records[0].status == "failed"
    assert records[0].next_retry_at == now + timedelta(seconds=42)


@pytest.mark.asyncio
async def test_dead_letter_after_repeated_failures(tmp_path, monkeypatch):
    path = tmp_path / "telegram_outbox.jsonl"
    monkeypatch.setattr(telegram_outbox, "MAX_ATTEMPTS", 2)
    enqueue_alert(alert_id="dead-id", message="hello", path=path, retry_after=0)
    _ready(load_outbox(path=path), path)

    async def fail(_message):
        return OutboxSendResult(False, error="network_down")

    await drain_pending(fail, path=path)
    records = load_outbox(path=path)
    _ready(records, path)

    stats = await drain_pending(fail, path=path)
    records = load_outbox(path=path)

    assert stats["dead_letter"] == 1
    assert records[0].status == "dead_letter"
    assert records[0].attempts == 2


@pytest.mark.asyncio
async def test_exception_does_not_drop_alert(tmp_path, monkeypatch):
    path = tmp_path / "telegram_outbox.jsonl"
    monkeypatch.setattr(telegram_outbox, "MAX_ATTEMPTS", 3)
    enqueue_alert(alert_id="exception-id", message="hello", path=path, retry_after=0)
    _ready(load_outbox(path=path), path)

    async def explode(_message):
        raise RuntimeError("socket exploded")

    stats = await drain_pending(explode, path=path)
    records = load_outbox(path=path)

    assert stats["failed"] == 1
    assert len(records) == 1
    assert records[0].status == "failed"
    assert records[0].last_error == "socket exploded"
