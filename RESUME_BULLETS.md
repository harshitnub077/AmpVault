# Escrowatt — Quantified Resume Bullets

The following 3 resume bullet points are generated using strictly measured, verifiable metrics from the Escrowatt test suite (`pytest`) and benchmark harness (`make bench` / `scripts/bench.py`).

---

### Bullet 1: Core Financial Ledger & Zero-Drift Concurrency
* **Bullet**:
  > Engineered an append-only double-entry ledger in async Python 3.11 / SQLAlchemy 2 with atomic balance increments and integer paise precision; validated zero balance drift (`0 paise`) under a 100-worker concurrent release stress test and enforced zero-sum invariant (`Σ Debits == Σ Credits`) across arbitrary multi-leg splits via Hypothesis property-based testing.
* **Measured Metric Proof**:
  - `tests/concurrency/test_concurrency_release.py`: 100 parallel workers produce exactly 1 payout and 0 balance drift.
  - `tests/property/test_ledger_properties.py`: 15 Hypothesis property iterations up to ₹1,00,00,000 paise with 0 drift.

---

### Bullet 2: Escrow State Machine & Split Payout Performance
* **Bullet**:
  > Architected a 7-stage finite state machine (`CREATED` → `RELEASED`) for B2B solar equipment procurement, automating multi-party split disbursements (seller, logistics, platform fee); benchmarked at **143.9 state transitions/sec** with **4.26ms p50 latency** and **17.28ms p95 latency** while maintaining an immutable audit log for every state transition.
* **Measured Metric Proof**:
  - `scripts/bench.py` / `docs/BENCHMARKS.md`: End-to-end lifecycle benchmark across 250 state transitions yielding 143.9 req/s throughput with 4.26ms p50 and 17.28ms p95 latency.

---

### Bullet 3: Dual-Layer Idempotency, Indian GST Engine & High Test Coverage
* **Bullet**:
  > Built an Indian statutory tax engine automating HSN 8541/8504 CGST/SGST vs IGST splits with Mod-36 GSTIN checksum validation, coupled with a dual-layer Redis + PostgreSQL idempotency guard and transactional outbox webhooks; achieved **89.24% test coverage** across 40 unit, property, and integration tests.
* **Measured Metric Proof**:
  - `pytest --cov=src`: 40 passing tests with **89.24% statement coverage** (`1,376 statements`, `148 misses`).
  - `src/tax/gst_engine.py`: 15-character Mod-36 check-digit validation and statutory Place of Supply rules.
