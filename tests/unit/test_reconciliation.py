import datetime

import pytest

from src.ledger.models import AccountType, PostingDirection
from src.ledger.schemas import AccountCreate, PostingCreate
from src.ledger.service import LedgerService
from src.reconciliation.engine import (
    GatewayPaymentRecord,
    ReconciliationEngine,
)


@pytest.mark.asyncio
async def test_nightly_reconciliation_zero_drift(db_session):
    ledger = LedgerService(db_session)
    rec_engine = ReconciliationEngine(db_session)

    bank = await ledger.create_account(AccountCreate(account_number="BANK-REC-01", name="Bank", type=AccountType.ASSET))
    escrow = await ledger.create_account(
        AccountCreate(account_number="ESCROW-REC-01", name="Escrow Hold", type=AccountType.LIABILITY)
    )

    amount = 10000000  # 1 Lakh INR (10M paise)
    await ledger.post_journal_entry(
        description="Escrow funding",
        reference_type="ESCROW_FUNDING",
        reference_id="ORD-REC-101",
        postings=[
            PostingCreate(account_id=bank.id, direction=PostingDirection.DEBIT, amount_paise=amount),
            PostingCreate(account_id=escrow.id, direction=PostingDirection.CREDIT, amount_paise=amount),
        ],
    )

    # Simulated gateway settlement record matching exactly
    gateway_records = [
        GatewayPaymentRecord(
            gateway_payment_id="pay_gw_101",
            escrow_order_id="ORD-REC-101",
            amount_paise=amount,
            status="CAPTURED",
            captured_at=datetime.datetime.now(datetime.timezone.utc),
        )
    ]

    report = await rec_engine.run_reconciliation(gateway_records)
    assert report.is_balanced is True
    assert report.total_drift_paise == 0
    assert report.matched_count == 1
    assert report.unmatched_count == 0


@pytest.mark.asyncio
async def test_nightly_reconciliation_detects_drift(db_session):
    ledger = LedgerService(db_session)
    rec_engine = ReconciliationEngine(db_session)

    bank = await ledger.create_account(AccountCreate(account_number="BANK-REC-02", name="Bank", type=AccountType.ASSET))
    escrow = await ledger.create_account(
        AccountCreate(account_number="ESCROW-REC-02", name="Escrow Hold", type=AccountType.LIABILITY)
    )

    # 1. Order in ledger with 10M paise
    await ledger.post_journal_entry(
        description="Escrow funding",
        reference_type="ESCROW_FUNDING",
        reference_id="ORD-REC-202",
        postings=[
            PostingCreate(account_id=bank.id, direction=PostingDirection.DEBIT, amount_paise=10000000),
            PostingCreate(account_id=escrow.id, direction=PostingDirection.CREDIT, amount_paise=10000000),
        ],
    )

    # Gateway has 9.5M paise for ORD-REC-202 (amount mismatch) + captured payment for unrecorded order ORD-REC-303
    gateway_records = [
        GatewayPaymentRecord(
            gateway_payment_id="pay_gw_202",
            escrow_order_id="ORD-REC-202",
            amount_paise=9500000,  # 50,000 paise short
            status="CAPTURED",
            captured_at=datetime.datetime.now(datetime.timezone.utc),
        ),
        GatewayPaymentRecord(
            gateway_payment_id="pay_gw_303",
            escrow_order_id="ORD-REC-303",
            amount_paise=4000000,
            status="CAPTURED",
            captured_at=datetime.datetime.now(datetime.timezone.utc),
        ),
    ]

    report = await rec_engine.run_reconciliation(gateway_records)
    assert report.is_balanced is False
    assert report.matched_count == 0
    assert report.unmatched_count == 2
    assert report.total_drift_paise == 500000 + 4000000  # 4.5M paise total drift
    assert len(report.discrepancies) == 2
