import datetime
import enum
import uuid

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class EscrowState(str, enum.Enum):
    CREATED = "CREATED"
    FUNDED = "FUNDED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RELEASED = "RELEASED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


class EscrowOrder(Base):
    __tablename__ = "escrow_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    buyer_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    seller_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    logistics_partner_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    equipment_hsn: Mapped[str] = mapped_column(String(8), default="8541", nullable=False)
    goods_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    logistics_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    buyer_gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    seller_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    place_of_supply_state: Mapped[str] = mapped_column(String(2), nullable=False)

    state: Mapped[EscrowState] = mapped_column(
        Enum(EscrowState), default=EscrowState.CREATED, nullable=False, index=True
    )
    escrow_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )

    tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    courier_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    inspection_deadline: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
        nullable=False,
    )

    audit_logs: Mapped[list["EscrowAuditLog"]] = relationship(
        "EscrowAuditLog", back_populates="escrow_order", cascade="all, delete-orphan", lazy="selectin"
    )


class EscrowAuditLog(Base):
    __tablename__ = "escrow_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    escrow_order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("escrow_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[EscrowState] = mapped_column(Enum(EscrowState), nullable=False)
    to_state: Mapped[EscrowState] = mapped_column(Enum(EscrowState), nullable=False)
    triggered_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    escrow_order: Mapped["EscrowOrder"] = relationship("EscrowOrder", back_populates="audit_logs")

    __table_args__ = (Index("ix_escrow_audit_order_created", "escrow_order_id", "created_at"),)
