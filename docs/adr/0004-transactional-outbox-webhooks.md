# ADR 0004: Transactional Outbox Pattern for Webhook Dispatch

## Status
Accepted

## Context
When an escrow state changes, external parties (buyer, seller, courier, gateway) must be notified via outbound webhooks. Making network calls directly inside the HTTP request transaction creates distributed transaction anomalies (e.g. webhook sent, but DB transaction rolled back; or DB committed, but server crashed before webhook dispatch).

## Decision
1. Adopt the **Transactional Outbox Pattern**:
   - Write an `OutboxEvent` record to the database in the exact same transaction as the escrow state change.
2. An asynchronous background dispatcher worker continuously polls for unprocessed outbox events:
   - Dispatches webhook payloads signed with HMAC-SHA256.
   - Applies exponential backoff (`delay = base * 2 ^ retry_count`).
   - Caps max retries at 5 attempts before marking as `DEAD_LETTER`.
3. Inbound webhooks (from payment gateway, logistics) are verified via HMAC-SHA256 signature, checked against a 300-second timestamp drift window to prevent replay attacks, and deduplicated via a `webhook_events` registry.

## Consequences
- Guaranteed at-least-once delivery of outbound events.
- Decouples core transaction latency from external HTTP webhook latency.
