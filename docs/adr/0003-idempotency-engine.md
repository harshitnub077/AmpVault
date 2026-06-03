# ADR 0003: Dual-Layer Idempotency Key Engine

## Status
Accepted

## Context
Network timeouts and client retries on payment or payout endpoints can lead to double-charging or duplicate disbursements. Clients must be able to safely retry HTTP requests without causing duplicate side effects.

## Decision
1. Require an `Idempotency-Key` HTTP header (UUIDv4 or client-defined string) on all mutating financial endpoints (`POST /api/v1/escrow/{id}/fund`, `POST /api/v1/escrow/{id}/release`, `POST /api/v1/escrow/{id}/refund`).
2. Implement a two-layer defense:
   - **Layer 1 (Fast atomic barrier)**: Redis key reservation with `SET key lock_value NX EX 120`. If the key already exists and is locked, return HTTP `409 Conflict` (request in progress).
   - **Layer 2 (Durable persistence)**: PostgreSQL table `idempotency_keys` storing `(key, endpoint, request_hash, response_code, response_body, status, created_at)`.
3. If a request is received with an existing completed idempotency key, immediately return the cached response code and body without re-executing any business logic.
4. If a request arrives with the same idempotency key but a different request body hash, reject with HTTP `422 Unprocessable Entity` (key reused with mismatched payload).

## Consequences
- Zero double-charges even with 100+ concurrent retries.
- Fast sub-millisecond response for retried requests.
