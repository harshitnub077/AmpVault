# ADR 0005: Indian GST Engine & Solar Equipment HSN Calculation

## Status
Accepted

## Context
Solar equipment orders in India are subject to statutory Goods and Services Tax (GST). Solar photovoltaic modules (HSN 8541) and solar inverters (HSN 8504) attract specific GST rates. Furthermore, tax bifurcation depends on Place of Supply:
- Intra-state (Supplier State == Place of Supply): CGST (50%) + SGST (50%)
- Inter-state (Supplier State != Place of Supply): IGST (100%)
Logistics freight (HSN 9965) and Platform Escrow Fee (HSN 9983) attract 18% GST.

## Decision
1. Implement a pure-Python GST and HSN engine in `src/tax/gst_engine.py`.
2. Extract the 2-digit State Code directly from the first two characters of the 15-character GSTIN.
3. Validate GSTINs using the official Mod-36 check-digit algorithm.
4. Calculate taxes using integer paise arithmetic. Apply half-up rounding at the paise level and enforce that `CGST + SGST == Total Tax` down to the exact paise.

## Consequences
- Full statutory compliance with Indian tax regulations.
- Deterministic tax calculations with zero float rounding discrepancies.
