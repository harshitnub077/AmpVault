import asyncio

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.ledger.models import AccountType, PostingDirection
from src.ledger.schemas import AccountCreate, PostingCreate
from src.ledger.service import LedgerService


@given(
    st.integers(min_value=100, max_value=1_000_000_00),  # up to 10 Lakh INR (1M paise)
    st.integers(min_value=1, max_value=5),  # number of debit legs
    st.integers(min_value=1, max_value=5),  # number of credit legs
)
@hyp_settings(max_examples=15, deadline=None)
def test_hypothesis_ledger_always_balances(total_amount_paise: int, num_debits: int, num_credits: int):
    """
    Property-Based Test:
    For any arbitrary total amount partitioned into N debit legs and M credit legs:
    1. Sum of debits strictly equals sum of credits.
    2. Ledger service executes posting without error.
    3. Account integrity audit confirms zero balance drift across all participating accounts.
    """

    async def run():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            service = LedgerService(session)

            # Partition total_amount_paise across debits
            debit_shares = [total_amount_paise // num_debits] * num_debits
            debit_shares[-1] += total_amount_paise - sum(debit_shares)

            # Partition total_amount_paise across credits
            credit_shares = [total_amount_paise // num_credits] * num_credits
            credit_shares[-1] += total_amount_paise - sum(credit_shares)

            assert sum(debit_shares) == total_amount_paise
            assert sum(credit_shares) == total_amount_paise

            # Create debit accounts
            debit_accounts = []
            for i in range(num_debits):
                acc = await service.create_account(
                    AccountCreate(
                        account_number=f"DR-ACC-{i}",
                        name=f"Debit Account {i}",
                        type=AccountType.ASSET,
                    )
                )
                debit_accounts.append(acc)

            # Create credit accounts
            credit_accounts = []
            for j in range(num_credits):
                acc = await service.create_account(
                    AccountCreate(
                        account_number=f"CR-ACC-{j}",
                        name=f"Credit Account {j}",
                        type=AccountType.LIABILITY,
                    )
                )
                credit_accounts.append(acc)

            postings = [
                PostingCreate(
                    account_id=acc.id,
                    direction=PostingDirection.DEBIT,
                    amount_paise=amount,
                )
                for acc, amount in zip(debit_accounts, debit_shares, strict=False)
            ] + [
                PostingCreate(
                    account_id=acc.id,
                    direction=PostingDirection.CREDIT,
                    amount_paise=amount,
                )
                for acc, amount in zip(credit_accounts, credit_shares, strict=False)
            ]

            entry = await service.post_journal_entry(
                description=f"Property test entry for {total_amount_paise} paise",
                reference_type="PROPERTY_TEST",
                reference_id="HYPOTHESIS-001",
                postings=postings,
            )
            assert entry.id is not None

            # Verify integrity on all debit accounts
            for acc in debit_accounts:
                report = await service.verify_account_integrity(acc.id)
                assert report.is_valid is True
                assert report.drift_paise == 0

            # Verify integrity on all credit accounts
            for acc in credit_accounts:
                report = await service.verify_account_integrity(acc.id)
                assert report.is_valid is True
                assert report.drift_paise == 0

        await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()
