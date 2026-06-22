import datetime
import enum
import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class AccountType(str, enum.Enum):
    ASSET = "ASSET"  # e.g., Platform Bank Clearing, Cash
    LIABILITY = "LIABILITY"  # e.g., Escrow Holding, Seller Payable, Logistics Payable
    EQUITY = "EQUITY"  # e.g., Retained Earnings
    REVENUE = "REVENUE"  # e.g., Platform Escrow Fee Revenue
    EXPENSE = "EXPENSE"  # e.g., Gateway Processing Fees


class PostingDirection(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class JournalEntryStatus(str, enum.Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    balance_paise: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
    )

    postings: Mapped[list["Posting"]] = relationship("Posting", back_populates="account", lazy="selectin")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    reference_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[JournalEntryStatus] = mapped_column(
        Enum(JournalEntryStatus), default=JournalEntryStatus.POSTED, nullable=False, index=True
    )
    posted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    postings: Mapped[list["Posting"]] = relationship(
        "Posting", back_populates="journal_entry", lazy="selectin", cascade="all, delete-orphan"
    )


class Posting(Base):
    __tablename__ = "postings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    journal_entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    direction: Mapped[PostingDirection] = mapped_column(Enum(PostingDirection), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    journal_entry: Mapped["JournalEntry"] = relationship("JournalEntry", back_populates="postings", lazy="selectin")
    account: Mapped["Account"] = relationship("Account", back_populates="postings", lazy="selectin")

    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_postings_amount_positive"),
        Index("ix_postings_account_created", "account_id", "created_at"),
    )
