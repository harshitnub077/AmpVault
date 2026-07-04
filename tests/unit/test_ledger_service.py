import pydantic
import pytest

from src.core.exceptions import (
    AccountNotFoundError,
    InvalidAmountError,
    LedgerUnbalancedError,
)
from src.ledger.models import AccountType, JournalEntryStatus, PostingDirection
from src.ledger.schemas import AccountCreate, PostingCreate
from src.ledger.service import LedgerService


@pytest.mark.asyncio
async def test_create_account(db_session):
    service = LedgerService(db_session)
    acc = await service.create_account(
        AccountCreate(
            account_number="ACC-BANK-001",
            name="Platform Bank Clearing",
            type=AccountType.ASSET,
            currency="INR",
        )
    )
    assert acc.id is not None
    assert acc.account_number == "ACC-BANK-001"
    assert acc.balance_paise == 0

    fetched = await service.get_account(acc.id)
    assert fetched.id == acc.id
    assert fetched.name == "Platform Bank Clearing"


@pytest.mark.asyncio
async def test_post_balanced_journal_entry(db_session):
    service = LedgerService(db_session)
    bank = await service.create_account(
        AccountCreate(
            account_number="BANK-01",
            name="Platform Bank Clearing",
            type=AccountType.ASSET,
        )
    )
    escrow = await service.create_account(
        AccountCreate(
            account_number="ESCROW-ORDER-101",
            name="Escrow Liability Order #101",
            type=AccountType.LIABILITY,
        )
    )

    amount = 50000000  # 5,00,000 INR (50M paise)
    postings = [
        PostingCreate(account_id=bank.id, direction=PostingDirection.DEBIT, amount_paise=amount),
        PostingCreate(account_id=escrow.id, direction=PostingDirection.CREDIT, amount_paise=amount),
    ]

    entry = await service.post_journal_entry(
        description="Buyer funds deposit for Order #101",
        reference_type="ESCROW_DEPOSIT",
        reference_id="ORDER-101",
        postings=postings,
    )

    assert entry.id is not None
    assert entry.status == JournalEntryStatus.POSTED
    assert len(entry.postings) == 2

    # Check updated balances
    bank_acc = await service.get_account(bank.id)
    escrow_acc = await service.get_account(escrow.id)
    assert bank_acc.balance_paise == 50000000
    assert escrow_acc.balance_paise == 50000000

    # Verify zero drift audit
    report_bank = await service.verify_account_integrity(bank.id)
    report_escrow = await service.verify_account_integrity(escrow.id)
    assert report_bank.is_valid is True
    assert report_bank.drift_paise == 0
    assert report_escrow.is_valid is True
    assert report_escrow.drift_paise == 0


@pytest.mark.asyncio
async def test_unbalanced_entry_rejected(db_session):
    service = LedgerService(db_session)
    bank = await service.create_account(
        AccountCreate(
            account_number="BANK-02",
            name="Platform Bank",
            type=AccountType.ASSET,
        )
    )
    escrow = await service.create_account(
        AccountCreate(
            account_number="ESCROW-02",
            name="Escrow Hold",
            type=AccountType.LIABILITY,
        )
    )

    postings = [
        PostingCreate(account_id=bank.id, direction=PostingDirection.DEBIT, amount_paise=1000),
        PostingCreate(account_id=escrow.id, direction=PostingDirection.CREDIT, amount_paise=999),
    ]

    with pytest.raises(LedgerUnbalancedError) as exc_info:
        await service.post_journal_entry(
            description="Unbalanced transaction",
            reference_type="ESCROW",
            reference_id="TEST",
            postings=postings,
        )
    assert "Ledger entry unbalanced" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_amount_rejected(db_session):
    service = LedgerService(db_session)
    bank = await service.create_account(
        AccountCreate(account_number="BANK-03", name="Platform Bank", type=AccountType.ASSET)
    )
    escrow = await service.create_account(
        AccountCreate(account_number="ESCROW-03", name="Escrow Hold", type=AccountType.LIABILITY)
    )

    with pytest.raises((InvalidAmountError, pydantic.ValidationError)):
        PostingCreate(account_id=bank.id, direction=PostingDirection.DEBIT, amount_paise=0)


@pytest.mark.asyncio
async def test_nonexistent_account_rejected(db_session):
    service = LedgerService(db_session)
    bank = await service.create_account(
        AccountCreate(account_number="BANK-04", name="Platform Bank", type=AccountType.ASSET)
    )

    postings = [
        PostingCreate(account_id=bank.id, direction=PostingDirection.DEBIT, amount_paise=5000),
        PostingCreate(
            account_id="00000000-0000-0000-0000-000000000000", direction=PostingDirection.CREDIT, amount_paise=5000
        ),
    ]

    with pytest.raises(AccountNotFoundError):
        await service.post_journal_entry(
            description="Missing account transaction",
            reference_type="TEST",
            reference_id="TEST",
            postings=postings,
        )


@pytest.mark.asyncio
async def test_void_reversal_entry(db_session):
    service = LedgerService(db_session)
    bank = await service.create_account(AccountCreate(account_number="BANK-05", name="Bank", type=AccountType.ASSET))
    seller = await service.create_account(
        AccountCreate(account_number="SELLER-05", name="Seller Payable", type=AccountType.LIABILITY)
    )

    # Post initial disbursement
    entry = await service.post_journal_entry(
        description="Seller payout",
        reference_type="PAYOUT",
        reference_id="ORDER-500",
        postings=[
            PostingCreate(account_id=seller.id, direction=PostingDirection.DEBIT, amount_paise=25000),
            PostingCreate(account_id=bank.id, direction=PostingDirection.CREDIT, amount_paise=25000),
        ],
    )

    # Check intermediate balances
    b1 = await service.get_account(bank.id)
    s1 = await service.get_account(seller.id)
    assert b1.balance_paise == -25000
    assert s1.balance_paise == -25000

    # Void the entry with a reason
    reversal = await service.void_journal_entry(entry.id, reason="Incorrect bank routing number")
    assert reversal.status == JournalEntryStatus.POSTED

    # Check final balances returned to 0
    b2 = await service.get_account(bank.id)
    s2 = await service.get_account(seller.id)
    assert b2.balance_paise == 0
    assert s2.balance_paise == 0

    # Verify audit reports
    r_bank = await service.verify_account_integrity(bank.id)
    r_seller = await service.verify_account_integrity(seller.id)
    assert r_bank.drift_paise == 0
    assert r_seller.drift_paise == 0
