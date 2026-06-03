# ADR 0002: Deterministic Escrow State Machine with Audit Event Trail

## Status
Accepted

## Context
High-value solar equipment orders require strict state progression: agreement signing, funding, transit tracking, delivery confirmation, inspection window, dispute resolution, and fund release. An invalid state jump (e.g. `CREATED` to `RELEASED`) represents a critical security and financial breach.

## Decision
1. Implement an explicit state machine:
   - Valid states: `CREATED`, `FUNDED`, `IN_TRANSIT`, `DELIVERED`, `RELEASED`, `DISPUTED`, `REFUNDED`.
2. All state transitions must pass through a centralized transition validator. Any unauthorized transition raises an `IllegalStateTransitionError`.
3. Every state transition atomically writes an `EscrowAuditLog` row capturing:
   - `from_state`, `to_state`, `triggered_by_user_id`, `reason`, `metadata`, and timestamp.
4. State mutations that trigger monetary movement (e.g., `FUNDED`, `RELEASED`, `REFUNDED`) must execute inside the same database transaction as the corresponding double-entry journal entry.

## Consequences
- Guaranteed consistency between order lifecycle status and ledger liabilities.
- Complete regulatory and forensic audit trail for every dispute and payout.
