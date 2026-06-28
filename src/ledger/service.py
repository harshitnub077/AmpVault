import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.exceptions import (
    AccountNotFoundError,
    InvalidAmountError,
    LedgerUnbalancedError,
)
from src.ledger.models import (
    Account,
    AccountType,
    JournalEntry,
    JournalEntryStatus,
    Posting,
    PostingDirection,
)
from src.ledger.schemas import (
    AccountCreate,
    AccountIntegrityReport,
    PostingCreate,
)


class LedgerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_account(self, data: AccountCreate) -> Account:
        """Create a new ledger account with zero initial balance."""
        account = Account(
            account_number=data.account_number,
            name=data.name,
            type=data.type,
            currency=data.currency,
            balance_paise=0,
            is_active=True,
        )
        self.session.add(account)
        await self.session.flush()
        return account

    async def get_account(self, account_id: str) -> Account:
        """Retrieve an account by ID."""
        stmt = select(Account).where(Account.id == account_id)
        result = await self.session.execute(stmt)
        account = result.scalar_one_or_none()
        if not account:
            raise AccountNotFoundError(f"Account {account_id} not found")
        return account

    async def get_account_by_number(self, account_number: str) -> Account | None:
        """Retrieve an account by its unique account number."""
        stmt = select(Account).where(Account.account_number == account_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def post_journal_entry(
        self,
        description: str,
        reference_type: str,
        reference_id: str,
        postings: Sequence[PostingCreate],
    ) -> JournalEntry:
        """
        Post a double-entry journal entry atomically.
        Guarantees:
        1. sum(debits) == sum(credits) > 0.
        2. Every posting amount > 0 integer paise.
        3. Row-level locks on accounts sorted deterministically to prevent deadlocks.
        4. Atomic database-level balance increments (UPDATE ... SET balance_paise = balance_paise + delta).
        """
        if not postings or len(postings) < 2:
            raise LedgerUnbalancedError("A journal entry requires at least 2 postings")

        total_debits = 0
        total_credits = 0

        for p in postings:
            if p.amount_paise <= 0:
                raise InvalidAmountError(
                    f"Posting amount must be strictly positive integer paise, got {p.amount_paise}"
                )
            if p.direction == PostingDirection.DEBIT:
                total_debits += p.amount_paise
            elif p.direction == PostingDirection.CREDIT:
                total_credits += p.amount_paise

        if total_debits != total_credits:
            raise LedgerUnbalancedError(
                f"Ledger entry unbalanced: Total Debits ({total_debits} paise) != Total Credits ({total_credits} paise)"
            )

        # Deterministic ordering of account IDs to avoid DB deadlock
        distinct_account_ids = sorted({p.account_id for p in postings})

        # Lock accounts in order
        stmt = select(Account).where(Account.id.in_(distinct_account_ids)).order_by(Account.id.asc())
        bind = self.session.get_bind()
        if bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()

        result = await self.session.execute(stmt)
        accounts_map: dict[str, Account] = {acc.id: acc for acc in result.scalars().all()}

        for acc_id in distinct_account_ids:
            if acc_id not in accounts_map:
                raise AccountNotFoundError(f"Account {acc_id} does not exist in ledger")
            if not accounts_map[acc_id].is_active:
                raise AccountNotFoundError(f"Account {acc_id} is inactive")

        # Create Journal Entry
        entry = JournalEntry(
            id=str(uuid.uuid4()),
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            status=JournalEntryStatus.POSTED,
        )
        self.session.add(entry)
        await self.session.flush()

        # Calculate atomic deltas per account
        deltas: dict[str, int] = dict.fromkeys(distinct_account_ids, 0)

        for p in postings:
            acc = accounts_map[p.account_id]
            posting_record = Posting(
                id=str(uuid.uuid4()),
                journal_entry_id=entry.id,
                account_id=acc.id,
                direction=p.direction,
                amount_paise=p.amount_paise,
            )
            self.session.add(posting_record)

            if acc.type in (AccountType.ASSET, AccountType.EXPENSE):
                delta = p.amount_paise if p.direction == PostingDirection.DEBIT else -p.amount_paise
            else:
                delta = p.amount_paise if p.direction == PostingDirection.CREDIT else -p.amount_paise

            deltas[acc.id] += delta

        # Atomic SQL updates for each account
        for acc_id, net_delta in deltas.items():
            if net_delta != 0:
                update_stmt = (
                    update(Account).where(Account.id == acc_id).values(balance_paise=Account.balance_paise + net_delta)
                )
                await self.session.execute(update_stmt)

        await self.session.flush()

        entry_stmt = (
            select(JournalEntry).where(JournalEntry.id == entry.id).options(selectinload(JournalEntry.postings))
        )
        entry_res = await self.session.execute(entry_stmt)
        return entry_res.scalar_one()

    async def void_journal_entry(self, journal_entry_id: str, reason: str) -> JournalEntry:
        """
        Void a journal entry by posting an immutable reversing entry.
        Never deletes or modifies existing posting records!
        """
        stmt = (
            select(JournalEntry).where(JournalEntry.id == journal_entry_id).options(selectinload(JournalEntry.postings))
        )
        res = await self.session.execute(stmt)
        original_entry = res.scalar_one_or_none()
        if not original_entry:
            raise LedgerUnbalancedError(f"Journal entry {journal_entry_id} not found")

        if original_entry.status == JournalEntryStatus.VOIDED:
            raise LedgerUnbalancedError(f"Journal entry {journal_entry_id} is already voided")

        # Construct opposing postings (swap DEBIT <-> CREDIT)
        reversing_postings = [
            PostingCreate(
                account_id=p.account_id,
                direction=(
                    PostingDirection.CREDIT if p.direction == PostingDirection.DEBIT else PostingDirection.DEBIT
                ),
                amount_paise=p.amount_paise,
            )
            for p in original_entry.postings
        ]

        # Post reversal
        reversal_entry = await self.post_journal_entry(
            description=f"REVERSAL: {original_entry.description} (Reason: {reason})",
            reference_type="VOID_REVERSAL",
            reference_id=original_entry.id,
            postings=reversing_postings,
        )

        original_entry.status = JournalEntryStatus.VOIDED
        await self.session.flush()
        return reversal_entry

    async def verify_account_integrity(self, account_id: str) -> AccountIntegrityReport:
        """
        Audit the account by summing all historical postings and comparing
        against the cached balance. Guarantees 0-drift invariant.
        """
        account = await self.get_account(account_id)

        # Sum debits
        d_stmt = select(func.coalesce(func.sum(Posting.amount_paise), 0)).where(
            Posting.account_id == account_id,
            Posting.direction == PostingDirection.DEBIT,
        )
        d_res = await self.session.execute(d_stmt)
        total_debits = d_res.scalar_one()

        # Sum credits
        c_stmt = select(func.coalesce(func.sum(Posting.amount_paise), 0)).where(
            Posting.account_id == account_id,
            Posting.direction == PostingDirection.CREDIT,
        )
        c_res = await self.session.execute(c_stmt)
        total_credits = c_res.scalar_one()

        if account.type in (AccountType.ASSET, AccountType.EXPENSE):
            calculated_balance = total_debits - total_credits
        else:
            calculated_balance = total_credits - total_debits

        drift = account.balance_paise - calculated_balance
        return AccountIntegrityReport(
            account_id=account.id,
            account_number=account.account_number,
            cached_balance_paise=account.balance_paise,
            calculated_balance_paise=calculated_balance,
            drift_paise=drift,
            is_valid=(drift == 0),
        )
