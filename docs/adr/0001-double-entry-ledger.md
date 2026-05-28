# ADR 0001: Append-Only Double-Entry Ledger with Integer Paise

## Status
Accepted

## Context
Marketplace escrow platforms handle multi-party fund routing (buyer, seller, logistics, platform). Traditional single-balance columns (`balance = balance + X`) suffer from balance drift under race conditions, lack historical traceability, and make financial audits nearly impossible. Floating-point arithmetic (`0.1 + 0.2 != 0.3`) causes penny discrepancies.

## Decision
1. Implement a double-entry ledger based on Journal Entries and Postings.
2. Every transaction must be balanced: `Σ Debits == Σ Credits`.
3. Store all currency amounts as positive 64-bit integers in **paise** (`₹1.00 = 100 paise`). Floats are prohibited in monetary fields.
4. Ledger records are append-only. No `UPDATE` or `DELETE` statements are executed against `postings` or `journal_entries`. To cancel or correct an entry, a reversing entry is posted.
5. In order to ensure race-safety under concurrent transfers, accounts involved in a journal entry are locked using row-level locking (`SELECT FOR UPDATE`) ordered deterministically by account ID to prevent deadlocks.

## Consequences
- Complete mathematical certainty and auditability.
- No float precision errors.
- Slightly higher write amplification compared to single-row updates, compensated by indexed queries and balance snapshots.
