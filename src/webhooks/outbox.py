import datetime
import json
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.webhooks.models import OutboxEvent
from src.webhooks.verifier import sign_payload


async def schedule_outbox_event(
    session: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    destination_url: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """
    Write an outbox event atomically in the same DB transaction as business logic.
    Guarantees at-least-once delivery semantics without distributed 2PC.
    """
    event = OutboxEvent(
        id=str(uuid.uuid4()),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        destination_url=destination_url,
        payload=json.dumps(payload, default=str),
        status="PENDING",
        retry_count=0,
        max_retries=5,
        next_retry_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


class OutboxDispatcher:
    def __init__(self, session: AsyncSession, webhook_secret: str = "whsec_outbound_default_key") -> None:
        self.session = session
        self.secret = webhook_secret

    async def dispatch_pending_events(self, limit: int = 20, client: httpx.AsyncClient | None = None) -> int:
        """
        Poll pending outbox events whose next_retry_at <= now,
        dispatches with HMAC header, and applies exponential backoff on failure.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "PENDING",
                OutboxEvent.next_retry_at <= now,
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        events = list(res.scalars().all())

        if not events:
            return 0

        dispatched_count = 0
        should_close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=10.0)
            should_close_client = True

        try:
            for event in events:
                payload_bytes = event.payload.encode("utf-8")
                ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
                sig = sign_payload(payload_bytes, self.secret, ts)

                headers = {
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": sig,
                    "X-Webhook-Timestamp": str(ts),
                    "X-Event-Type": event.event_type,
                }

                try:
                    resp = await client.post(event.destination_url, content=payload_bytes, headers=headers)
                    if 200 <= resp.status_code < 300:
                        event.status = "SENT"
                        dispatched_count += 1
                    else:
                        self._handle_failure(event, f"HTTP {resp.status_code}: {resp.text[:200]}")
                except Exception as exc:
                    self._handle_failure(event, str(exc))

            await self.session.flush()
        finally:
            if should_close_client:
                await client.aclose()

        return dispatched_count

    def _handle_failure(self, event: OutboxEvent, error_msg: str) -> None:
        event.retry_count += 1
        event.last_error = error_msg
        if event.retry_count >= event.max_retries:
            event.status = "DEAD_LETTER"
        else:
            # Exponential backoff: 2, 4, 8, 16, 32 seconds
            delay_sec = 2**event.retry_count
            event.next_retry_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delay_sec)
