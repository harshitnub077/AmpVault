import fakeredis.aioredis
import pytest

from src.core.exceptions import (
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
)
from src.core.idempotency import IdempotencyEngine


@pytest.mark.asyncio
async def test_idempotency_first_call_acquires_lock(db_session):
    redis = fakeredis.aioredis.FakeRedis()
    engine = IdempotencyEngine(db_session, redis_client=redis)

    key = "idem-test-key-01"
    endpoint = "/api/v1/escrow/123/release"
    payload = {"reason": "Delivery accepted"}

    should_execute, code, body = await engine.acquire_lock_or_cached_response(
        key=key, endpoint=endpoint, payload=payload
    )
    assert should_execute is True
    assert code is None
    assert body is None

    # Simulate saving response
    await engine.save_response(key=key, status_code=200, response_body={"status": "RELEASED"})

    # Second call with same key and payload returns cached response
    should_execute_2, code_2, body_2 = await engine.acquire_lock_or_cached_response(
        key=key, endpoint=endpoint, payload=payload
    )
    assert should_execute_2 is False
    assert code_2 == 200
    assert "RELEASED" in body_2


@pytest.mark.asyncio
async def test_idempotency_payload_mismatch_rejected(db_session):
    redis = fakeredis.aioredis.FakeRedis()
    engine = IdempotencyEngine(db_session, redis_client=redis)

    key = "idem-test-key-02"
    endpoint = "/api/v1/escrow/456/release"

    # Initial request
    await engine.acquire_lock_or_cached_response(key=key, endpoint=endpoint, payload={"amount": 1000})
    await engine.save_response(key=key, status_code=200, response_body={"ok": True})

    # Second request with same key but altered payload
    with pytest.raises(IdempotencyPayloadMismatchError):
        await engine.acquire_lock_or_cached_response(key=key, endpoint=endpoint, payload={"amount": 9999})


@pytest.mark.asyncio
async def test_idempotency_in_flight_conflict(db_session):
    redis = fakeredis.aioredis.FakeRedis()
    engine = IdempotencyEngine(db_session, redis_client=redis)

    key = "idem-test-key-03"
    endpoint = "/api/v1/escrow/789/release"

    # First request begins execution (no save_response yet)
    should_run, _, _ = await engine.acquire_lock_or_cached_response(key=key, endpoint=endpoint, payload={"foo": "bar"})
    assert should_run is True

    # Concurrent second request arrives while first is still pending
    with pytest.raises(IdempotencyConflictError):
        await engine.acquire_lock_or_cached_response(key=key, endpoint=endpoint, payload={"foo": "bar"})
