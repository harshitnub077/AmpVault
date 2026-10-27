import time

import httpx
import pytest

from src.core.exceptions import WebhookVerificationError
from src.webhooks.outbox import OutboxDispatcher, schedule_outbox_event
from src.webhooks.verifier import sign_payload, verify_webhook_signature
from src.webhooks.worker import run_worker


def test_webhook_signature_verification_success():
    secret = "whsec_test_secret_123"
    body = b'{"event":"payment.captured","amount_paise":100000}'
    ts = int(time.time())
    sig = sign_payload(body, secret, ts)

    assert verify_webhook_signature(body, sig, str(ts), secret) is True


def test_webhook_signature_mismatch():
    secret = "whsec_test_secret_123"
    body = b'{"event":"payment.captured"}'
    ts = int(time.time())

    with pytest.raises(WebhookVerificationError) as exc:
        verify_webhook_signature(body, "invalidsignature123", str(ts), secret)
    assert "signature mismatch" in str(exc.value)


def test_webhook_timestamp_drift_replay_protection():
    secret = "whsec_test_secret_123"
    body = b'{"event":"payment.captured"}'
    expired_ts = int(time.time()) - 600  # 10 minutes ago (> 300s)
    sig = sign_payload(body, secret, expired_ts)

    with pytest.raises(WebhookVerificationError) as exc:
        verify_webhook_signature(body, sig, str(expired_ts), secret, max_drift_seconds=300)
    assert "timestamp drifted" in str(exc.value)


@pytest.mark.asyncio
async def test_outbox_event_scheduling_and_dispatch(db_session):
    # 1. Schedule an outbox event
    event = await schedule_outbox_event(
        session=db_session,
        event_type="escrow.released",
        aggregate_type="ESCROW",
        aggregate_id="ORD-999",
        destination_url="https://webhook.mock-receiver.internal/events",
        payload={"order_id": "ORD-999", "status": "RELEASED"},
    )
    assert event.id is not None
    assert event.status == "PENDING"
    assert event.retry_count == 0

    # 2. Dispatch with mock HTTP client
    mock_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"received": True}))
    async with httpx.AsyncClient(transport=mock_transport) as mock_client:
        dispatcher = OutboxDispatcher(db_session, webhook_secret="test_secret")
        dispatched = await dispatcher.dispatch_pending_events(client=mock_client)
        assert dispatched == 1

    assert event.status == "SENT"


@pytest.mark.asyncio
async def test_outbox_exponential_backoff_on_failure(db_session):
    event = await schedule_outbox_event(
        session=db_session,
        event_type="escrow.funded",
        aggregate_type="ESCROW",
        aggregate_id="ORD-FAIL",
        destination_url="https://flaky.mock-receiver.internal/events",
        payload={"order_id": "ORD-FAIL"},
    )

    # Dispatch against 500 error endpoint
    mock_transport = httpx.MockTransport(lambda req: httpx.Response(500, text="Internal Server Error"))
    async with httpx.AsyncClient(transport=mock_transport) as mock_client:
        dispatcher = OutboxDispatcher(db_session)
        dispatched = await dispatcher.dispatch_pending_events(client=mock_client)
        assert dispatched == 0

    assert event.status == "PENDING"
    assert event.retry_count == 1
    assert "HTTP 500" in event.last_error


@pytest.mark.asyncio
async def test_outbox_worker_run_once():
    # Verify worker executes run_once poll without error
    await run_worker(poll_interval=0.1, run_once=True)
