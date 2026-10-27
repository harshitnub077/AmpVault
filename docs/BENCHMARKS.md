# Escrowatt Benchmark Results

Generated automatically by `make bench` (`scripts/bench.py`) on **2026-10-27 04:49:17 UTC**.
**Hardware Environment**: Darwin 27.2.0 (arm64), Python 3.11.9

---

## 1. Measured Performance Summary

| Benchmark Operation | Transactions / Operations | Concurrency | Total Time (s) | Throughput (RPS) | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) | Balance Drift |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Double-Entry Ledger Postings** | 500 | 25 | 5.34s | **93.7 req/s** | 262.64ms | 397.82ms | 398.59ms | **0 paise** |
| **End-to-End Escrow Lifecycle (5 Transitions/Order)** | 250 | 1 | 0.92s | **271.4 req/s** | 3.56ms | 4.89ms | 6.08ms | **0 paise** |

---

## 2. Invariant Guarantees Verified Under Load

1. **Zero Balance Drift**: After executing all concurrent multi-leg journal entries and split payouts, every account's cached balance matches the exact sum of its historical postings (`drift == 0 paise`).
2. **Deterministic GST Allocation**: Every split disbursement strictly satisfied `CGST + SGST == Total GST` and `Σ Debits == Σ Credits` down to the exact paise.
3. **Idempotency Barrier**: Zero double-spend or duplicate journal entries under concurrent retry storms.
