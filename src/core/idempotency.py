import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.exceptions import (
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)  # PENDING, RESOLVED
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
    )

    __table_args__ = (Index("ix_idempotency_key_status", "key", "status"),)


def compute_payload_hash(payload: Any) -> str:
    """Compute deterministic SHA-256 hash of request payload."""
    if payload is None:
        raw_bytes = b""
    elif isinstance(payload, bytes):
        raw_bytes = payload
    elif isinstance(payload, str):
        raw_bytes = payload.encode("utf-8")
    else:
        raw_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


class IdempotencyEngine:
    def __init__(self, session: AsyncSession, redis_client: Any = None) -> None:
        self.session = session
        self.redis = redis_client

    async def acquire_lock_or_cached_response(
        self, key: str, endpoint: str, payload: Any
    ) -> tuple[bool, int | None, str | None]:
        """
        Check idempotency status:
        Returns:
        - (True, None, None): Key successfully locked; proceed with execution.
        - (False, status_code, body): Cached response available; return immediately without executing.
        Raises:
        - IdempotencyConflictError: If request with same key is currently in-flight.
        - IdempotencyPayloadMismatchError: If same key was previously used with different payload.
        """
        request_hash = compute_payload_hash(payload)

        # 1. Fast Layer: Redis atomic reservation
        if self.redis is not None:
            redis_lock_key = f"idemp:lock:{key}"
            # Attempt atomic lock for 120s
            acquired = await self.redis.set(redis_lock_key, "IN_PROGRESS", ex=120, nx=True)
            if not acquired:
                # Key already exists in Redis
                cached_data = await self.redis.get(f"idemp:cached:{key}")
                if cached_data:
                    try:
                        parsed = json.loads(cached_data)
                        if parsed.get("hash") != request_hash:
                            raise IdempotencyPayloadMismatchError(
                                f"Idempotency key '{key}' was reused with a different request payload."
                            )
                        return False, parsed["status_code"], parsed["body"]
                    except (json.JSONDecodeError, KeyError):
                        pass
                raise IdempotencyConflictError(
                    f"A request with Idempotency-Key '{key}' is already in progress. Please retry after completion."
                )

        # 2. Durable Layer: Database inspection
        stmt = select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()

        if record:
            if record.request_hash != request_hash:
                raise IdempotencyPayloadMismatchError(
                    f"Idempotency key '{key}' was reused with a different request payload."
                )
            if record.status == "RESOLVED":
                return False, record.response_code, record.response_body
            else:
                raise IdempotencyConflictError(
                    f"A request with Idempotency-Key '{key}' is currently pending processing."
                )

        # Insert new pending record
        import uuid

        new_record = IdempotencyRecord(
            id=str(uuid.uuid4()),
            key=key,
            endpoint=endpoint,
            request_hash=request_hash,
            status="PENDING",
        )
        self.session.add(new_record)
        await self.session.flush()

        return True, None, None

    async def save_response(self, key: str, status_code: int, response_body: Any) -> None:
        """Cache successful execution result in both DB and Redis."""
        body_str = response_body if isinstance(response_body, str) else json.dumps(response_body, default=str)

        stmt = select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            record.status = "RESOLVED"
            record.response_code = status_code
            record.response_body = body_str
            await self.session.flush()

        if self.redis is not None:
            # Store cached result and clear in-progress lock
            cached_payload = json.dumps(
                {"status_code": status_code, "body": body_str, "hash": record.request_hash if record else ""}
            )
            await self.redis.set(f"idemp:cached:{key}", cached_payload, ex=86400)  # 24h cache
            await self.redis.delete(f"idemp:lock:{key}")
