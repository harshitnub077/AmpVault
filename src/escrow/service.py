import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.config import get_settings
from src.core.exceptions import (
    DisputeResolutionError,
    EscrowNotFoundError,
)
from src.escrow.models import EscrowAuditLog, EscrowOrder, EscrowState
from src.escrow.schemas import (
    EscrowCreate,
    EscrowDeliverRequest,
    EscrowDispatchRequest,
    EscrowDisputeRequest,
    EscrowFundRequest,
    EscrowResolveRequest,
)
from src.escrow.state_machine import validate_transition
from src.ledger.models import AccountType, PostingDirection
from src.ledger.schemas import AccountCreate, PostingCreate
from src.ledger.service import LedgerService
from src.tax.split_calculator import compute_escrow_split_payout

settings = get_settings()


class EscrowService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ledger = LedgerService(session)

    async def _get_or_create_account(self, account_number: str, name: str, account_type: AccountType) -> str:
        """Helper to get existing account by account number or create a new one."""
        acc = await self.ledger.get_account_by_number(account_number)
        if not acc:
            acc = await self.ledger.create_account(
                AccountCreate(
                    account_number=account_number,
                    name=name,
                    type=account_type,
                    currency="INR",
                )
            )
        return acc.id

    async def get_escrow_order(self, escrow_id: str) -> EscrowOrder:
        """Retrieve an escrow order by ID with audit logs loaded."""
        stmt = (
            select(EscrowOrder)
            .execution_options(populate_existing=True)
            .where(EscrowOrder.id == escrow_id)
            .options(selectinload(EscrowOrder.audit_logs))
        )
        res = await self.session.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            raise EscrowNotFoundError(f"Escrow order {escrow_id} not found")
        return order

    async def get_by_order_number(self, order_number: str) -> EscrowOrder | None:
        """Retrieve an escrow order by its unique order number."""
        stmt = (
            select(EscrowOrder)
            .execution_options(populate_existing=True)
            .where(EscrowOrder.order_number == order_number)
            .options(selectinload(EscrowOrder.audit_logs))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_escrow(self, data: EscrowCreate) -> EscrowOrder:
        """
        Create a new escrow contract:
        1. Calculate GST breakdown and split payout.
        2. Create a dedicated Escrow Holding account in the ledger.
        3. Persist the EscrowOrder with state CREATED.
        4. Write initial audit log.
        """
        split = compute_escrow_split_payout(
            goods_base_amount_paise=data.goods_base_amount_paise,
            equipment_hsn=data.equipment_hsn,
            seller_gstin=data.seller_gstin,
            place_of_supply_state_code=data.place_of_supply_state,
            logistics_base_amount_paise=data.logistics_base_amount_paise,
            platform_fee_bps=settings.PLATFORM_ESCROW_FEE_BPS,
        )

        escrow_acc_number = f"ESCROW-HOLD-{data.order_number}"
        escrow_acc = await self.ledger.create_account(
            AccountCreate(
                account_number=escrow_acc_number,
                name=f"Escrow Liability: Order {data.order_number}",
                type=AccountType.LIABILITY,
                currency="INR",
            )
        )

        order_id = str(uuid.uuid4())
        order = EscrowOrder(
            id=order_id,
            order_number=data.order_number,
            buyer_id=data.buyer_id,
            seller_id=data.seller_id,
            logistics_partner_id=data.logistics_partner_id,
            equipment_hsn=data.equipment_hsn,
            goods_amount_paise=split.order_amount_paise,
            logistics_amount_paise=split.logistics_amount_paise,
            platform_fee_paise=split.platform_fee_paise,
            total_amount_paise=split.total_escrow_deposit_paise,
            currency="INR",
            buyer_gstin=data.buyer_gstin,
            seller_gstin=data.seller_gstin,
            place_of_supply_state=data.place_of_supply_state,
            state=EscrowState.CREATED,
            escrow_account_id=escrow_acc.id,
        )
        self.session.add(order)

        audit = EscrowAuditLog(
            id=str(uuid.uuid4()),
            escrow_order_id=order_id,
            from_state=EscrowState.CREATED,
            to_state=EscrowState.CREATED,
            triggered_by_user_id=data.buyer_id,
            event_type="ESCROW_CREATED",
            notes=f"Escrow order created with total deposit requirement of {split.total_escrow_deposit_paise} paise",
        )
        self.session.add(audit)
        await self.session.flush()

        return await self.get_escrow_order(order_id)

    async def fund_escrow(self, escrow_id: str, data: EscrowFundRequest) -> EscrowOrder:
        """
        Transition: CREATED -> FUNDED.
        Executes double-entry posting:
        DEBIT: Platform Bank Clearing (Asset)
        CREDIT: Escrow Holding Account (Liability)
        """
        order = await self.get_escrow_order(escrow_id)
        validate_transition(order.state, EscrowState.FUNDED)

        bank_acc_id = await self._get_or_create_account(
            account_number="BANK-CLEARING-INR",
            name="Platform Bank Clearing Account",
            account_type=AccountType.ASSET,
        )

        # Post double-entry journal entry
        await self.ledger.post_journal_entry(
            description=f"Buyer deposit for Escrow #{order.order_number} (Ref: {data.payment_reference})",
            reference_type="ESCROW_FUNDING",
            reference_id=order.id,
            postings=[
                PostingCreate(
                    account_id=bank_acc_id,
                    direction=PostingDirection.DEBIT,
                    amount_paise=order.total_amount_paise,
                ),
                PostingCreate(
                    account_id=order.escrow_account_id,
                    direction=PostingDirection.CREDIT,
                    amount_paise=order.total_amount_paise,
                ),
            ],
        )

        order.state = EscrowState.FUNDED
        audit = EscrowAuditLog(
            id=str(uuid.uuid4()),
            escrow_order_id=order.id,
            from_state=EscrowState.CREATED,
            to_state=EscrowState.FUNDED,
            triggered_by_user_id=data.buyer_user_id,
            event_type="ESCROW_FUNDED",
            notes=f"Payment verified via reference {data.payment_reference}",
        )
        self.session.add(audit)
        await self.session.flush()

        return await self.get_escrow_order(order.id)

    async def dispatch_escrow(self, escrow_id: str, data: EscrowDispatchRequest) -> EscrowOrder:
        """
        Transition: FUNDED -> IN_TRANSIT.
        Seller attaches courier name and tracking number.
        """
        order = await self.get_escrow_order(escrow_id)
        validate_transition(order.state, EscrowState.IN_TRANSIT)

        order.tracking_number = data.tracking_number
        order.courier_name = data.courier_name
        order.state = EscrowState.IN_TRANSIT

        audit = EscrowAuditLog(
            id=str(uuid.uuid4()),
            escrow_order_id=order.id,
            from_state=EscrowState.FUNDED,
            to_state=EscrowState.IN_TRANSIT,
            triggered_by_user_id=data.seller_user_id,
            event_type="ESCROW_DISPATCHED",
            notes=f"Goods dispatched with {data.courier_name}, Tracking #{data.tracking_number}",
        )
        self.session.add(audit)
        await self.session.flush()

        return await self.get_escrow_order(order.id)

    async def deliver_escrow(self, escrow_id: str, data: EscrowDeliverRequest) -> EscrowOrder:
        """
        Transition: IN_TRANSIT -> DELIVERED.
        Starts buyer inspection window (72 hours).
        """
        order = await self.get_escrow_order(escrow_id)
        validate_transition(order.state, EscrowState.DELIVERED)

        now = datetime.datetime.now(datetime.timezone.utc)
        order.inspection_deadline = now + datetime.timedelta(hours=settings.INSPECTION_WINDOW_HOURS)
        order.state = EscrowState.DELIVERED

        audit = EscrowAuditLog(
            id=str(uuid.uuid4()),
            escrow_order_id=order.id,
            from_state=EscrowState.IN_TRANSIT,
            to_state=EscrowState.DELIVERED,
            triggered_by_user_id=data.logistics_user_id,
            event_type="ESCROW_DELIVERED",
            notes=f"Proof of Delivery verified: {data.proof_of_delivery_ref}. Inspection window ends {order.inspection_deadline.isoformat()}",
        )
        self.session.add(audit)
        await self.session.flush()

        return await self.get_escrow_order(order.id)

    async def release_escrow(
        self, escrow_id: str, triggered_by_user_id: str, reason: str = "Buyer approved delivery"
    ) -> EscrowOrder:
        """
        Transition: DELIVERED -> RELEASED (or DISPUTED -> RELEASED).
        Executes multi-leg split payouts journal entry:
        DEBIT:  Escrow Holding Account (Total Order Amount)
        CREDIT: Seller Payable (Net Goods + Goods GST)
        CREDIT: Logistics Partner Payable (Logistics Fee + GST)
        CREDIT: Platform Fee Revenue (Base Commission + GST)
        Guarantees: Σ Debits == Σ Credits down to exact paise.
        """
        order = await self.get_escrow_order(escrow_id)
        validate_transition(order.state, EscrowState.RELEASED)

        # Get accounts for disbursement
        seller_acc_id = await self._get_or_create_account(
            account_number=f"PAYABLE-SELLER-{order.seller_id}",
            name=f"Seller Payable: {order.seller_id}",
            account_type=AccountType.LIABILITY,
        )
        logistics_acc_id = await self._get_or_create_account(
            account_number=f"PAYABLE-LOGISTICS-{order.logistics_partner_id}",
            name=f"Logistics Payable: {order.logistics_partner_id}",
            account_type=AccountType.LIABILITY,
        )
        platform_revenue_acc_id = await self._get_or_create_account(
            account_number="REVENUE-PLATFORM-ESCROW-FEES",
            name="Platform Escrow Fee Revenue",
            account_type=AccountType.REVENUE,
        )

        seller_credit = order.goods_amount_paise
        logistics_credit = order.logistics_amount_paise
        platform_fee_credit = order.platform_fee_paise

        assert seller_credit + logistics_credit + platform_fee_credit == order.total_amount_paise

        postings = [
            PostingCreate(
                account_id=order.escrow_account_id,
                direction=PostingDirection.DEBIT,
                amount_paise=order.total_amount_paise,
            ),
            PostingCreate(
                account_id=seller_acc_id,
                direction=PostingDirection.CREDIT,
                amount_paise=seller_credit,
            ),
            PostingCreate(
                account_id=logistics_acc_id,
                direction=PostingDirection.CREDIT,
                amount_paise=logistics_credit,
            ),
            PostingCreate(
                account_id=platform_revenue_acc_id,
                direction=PostingDirection.CREDIT,
                amount_paise=platform_fee_credit,
            ),
        ]

        await self.ledger.post_journal_entry(
            description=f"Escrow release & split payout for #{order.order_number}",
            reference_type="ESCROW_RELEASE_SPLIT",
            reference_id=order.id,
            postings=postings,
        )

        from_state = order.state
        order.state = EscrowState.RELEASED

        audit = EscrowAuditLog(
            id=str(uuid.uuid4()),
            escrow_order_id=order.id,
            from_state=from_state,
            to_state=EscrowState.RELEASED,
            triggered_by_user_id=triggered_by_user_id,
            event_type="ESCROW_RELEASED",
            notes=reason,
        )
        self.session.add(audit)
        await self.session.flush()

        return await self.get_escrow_order(order.id)

    async def refund_escrow(self, escrow_id: str, triggered_by_user_id: str, reason: str) -> EscrowOrder:
        """
        Transition: FUNDED -> REFUNDED or DISPUTED -> REFUNDED.
        Executes reversing journal entry:
        DEBIT:  Escrow Holding Account
        CREDIT: Buyer Refund Payable Account
        """
        order = await self.get_escrow_order(escrow_id)
        validate_transition(order.state, EscrowState.REFUNDED)

        buyer_refund_acc_id = await self._get_or_create_account(
            account_number=f"PAYABLE-BUYER-REFUND-{order.buyer_id}",
            name=f"Buyer Refund Payable: {order.buyer_id}",
            account_type=AccountType.LIABILITY,
        )

        await self.ledger.post_journal_entry(
            description=f"Escrow refund for #{order.order_number} (Reason: {reason})",
            reference_type="ESCROW_REFUND",
            reference_id=order.id,
            postings=[
                PostingCreate(
                    account_id=order.escrow_account_id,
                    direction=PostingDirection.DEBIT,
                    amount_paise=order.total_amount_paise,
                ),
                PostingCreate(
                    account_id=buyer_refund_acc_id,
                    direction=PostingDirection.CREDIT,
                    amount_paise=order.total_amount_paise,
                ),
            ],
        )

        from_state = order.state
        order.state = EscrowState.REFUNDED

        audit = EscrowAuditLog(
            id=str(uuid.uuid4()),
            escrow_order_id=order.id,
            from_state=from_state,
            to_state=EscrowState.REFUNDED,
            triggered_by_user_id=triggered_by_user_id,
            event_type="ESCROW_REFUNDED",
            notes=reason,
        )
        self.session.add(audit)
        await self.session.flush()

        return await self.get_escrow_order(order.id)

    async def dispute_escrow(self, escrow_id: str, data: EscrowDisputeRequest) -> EscrowOrder:
        """
        Transition: IN_TRANSIT -> DISPUTED or DELIVERED -> DISPUTED.
        Halts auto-release and freezes funds pending admin resolution.
        """
        order = await self.get_escrow_order(escrow_id)
        validate_transition(order.state, EscrowState.DISPUTED)

        from_state = order.state
        order.state = EscrowState.DISPUTED
        order.dispute_reason = data.reason

        audit = EscrowAuditLog(
            id=str(uuid.uuid4()),
            escrow_order_id=order.id,
            from_state=from_state,
            to_state=EscrowState.DISPUTED,
            triggered_by_user_id=data.disputed_by_user_id,
            event_type="ESCROW_DISPUTED",
            notes=f"Dispute raised: {data.reason}",
        )
        self.session.add(audit)
        await self.session.flush()

        return await self.get_escrow_order(order.id)

    async def resolve_dispute(self, escrow_id: str, data: EscrowResolveRequest) -> EscrowOrder:
        """
        Admin resolves dispute:
        - If decision is RELEASED: releases split funds to seller and logistics.
        - If decision is REFUNDED: returns funds to buyer.
        """
        order = await self.get_escrow_order(escrow_id)
        if order.state != EscrowState.DISPUTED:
            raise DisputeResolutionError(
                f"Cannot resolve dispute on order in state '{order.state.value}'. Order must be in DISPUTED state."
            )

        if data.decision == EscrowState.RELEASED:
            return await self.release_escrow(
                escrow_id,
                triggered_by_user_id=data.admin_user_id,
                reason=f"Admin Resolution (Seller Favored): {data.resolution_notes}",
            )
        elif data.decision == EscrowState.REFUNDED:
            return await self.refund_escrow(
                escrow_id,
                triggered_by_user_id=data.admin_user_id,
                reason=f"Admin Resolution (Buyer Favored): {data.resolution_notes}",
            )
        else:
            raise DisputeResolutionError(
                f"Invalid dispute resolution decision '{data.decision}'. Must be RELEASED or REFUNDED."
            )
