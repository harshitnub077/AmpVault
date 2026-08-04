import pytest

from src.core.exceptions import (
    IllegalStateTransitionError,
)
from src.escrow.models import EscrowState
from src.escrow.schemas import (
    EscrowCreate,
    EscrowDeliverRequest,
    EscrowDispatchRequest,
    EscrowDisputeRequest,
    EscrowFundRequest,
    EscrowResolveRequest,
)
from src.escrow.service import EscrowService
from src.ledger.service import LedgerService


@pytest.mark.asyncio
async def test_escrow_full_lifecycle_happy_path(db_session):
    escrow_svc = EscrowService(db_session)
    ledger_svc = LedgerService(db_session)

    # 1. Create Escrow Order
    order = await escrow_svc.create_escrow(
        EscrowCreate(
            order_number="SOLAR-ORD-2026-001",
            buyer_id="BUYER-USR-01",
            seller_id="SELLER-USR-01",
            logistics_partner_id="LOGISTICS-USR-01",
            equipment_hsn="8541",
            goods_base_amount_paise=20000000,  # 2 Lakh INR
            logistics_base_amount_paise=1000000,  # 10,000 INR
            seller_gstin="27AAPFU0939F1ZV",
            buyer_gstin="27AAPFU0939F1ZV",
            place_of_supply_state="27",
        )
    )

    assert order.state == EscrowState.CREATED
    assert len(order.audit_logs) == 1
    assert order.audit_logs[0].event_type == "ESCROW_CREATED"

    # Verify Escrow liability account was created with 0 balance
    hold_acc = await ledger_svc.get_account(order.escrow_account_id)
    assert hold_acc.balance_paise == 0

    # 2. Fund Escrow (CREATED -> FUNDED)
    funded = await escrow_svc.fund_escrow(
        order.id,
        EscrowFundRequest(
            buyer_user_id="BUYER-USR-01",
            payment_reference="PG-TXN-99887766",
        ),
    )
    assert funded.state == EscrowState.FUNDED
    assert len(funded.audit_logs) == 2

    # Check that escrow holding account now has the funded balance
    hold_acc = await ledger_svc.get_account(order.escrow_account_id)
    assert hold_acc.balance_paise == order.total_amount_paise

    # 3. Dispatch Goods (FUNDED -> IN_TRANSIT)
    in_transit = await escrow_svc.dispatch_escrow(
        order.id,
        EscrowDispatchRequest(
            seller_user_id="SELLER-USR-01",
            courier_name="Delhivery Express",
            tracking_number="DEL-TRK-771122",
        ),
    )
    assert in_transit.state == EscrowState.IN_TRANSIT
    assert in_transit.tracking_number == "DEL-TRK-771122"

    # 4. Deliver Goods (IN_TRANSIT -> DELIVERED)
    delivered = await escrow_svc.deliver_escrow(
        order.id,
        EscrowDeliverRequest(
            logistics_user_id="LOGISTICS-USR-01",
            proof_of_delivery_ref="POD-SIG-PHOTO-HASH-1234",
        ),
    )
    assert delivered.state == EscrowState.DELIVERED
    assert delivered.inspection_deadline is not None

    # 5. Release Escrow & Split Payout (DELIVERED -> RELEASED)
    released = await escrow_svc.release_escrow(
        order.id,
        triggered_by_user_id="BUYER-USR-01",
        reason="Buyer verified solar panels and inverter wattage",
    )
    assert released.state == EscrowState.RELEASED
    assert len(released.audit_logs) == 5

    # Check that escrow holding account returned to 0
    hold_acc = await ledger_svc.get_account(order.escrow_account_id)
    assert hold_acc.balance_paise == 0

    # Verify seller received net payout
    seller_acc = await ledger_svc.get_account_by_number(f"PAYABLE-SELLER-{order.seller_id}")
    assert seller_acc is not None
    assert seller_acc.balance_paise == order.goods_amount_paise

    # Verify logistics received payout
    logistics_acc = await ledger_svc.get_account_by_number(f"PAYABLE-LOGISTICS-{order.logistics_partner_id}")
    assert logistics_acc is not None
    assert logistics_acc.balance_paise == order.logistics_amount_paise

    # Verify platform revenue received commission
    rev_acc = await ledger_svc.get_account_by_number("REVENUE-PLATFORM-ESCROW-FEES")
    assert rev_acc is not None
    assert rev_acc.balance_paise == order.platform_fee_paise

    # Check zero drift across all accounts
    r_hold = await ledger_svc.verify_account_integrity(hold_acc.id)
    r_seller = await ledger_svc.verify_account_integrity(seller_acc.id)
    r_logistics = await ledger_svc.verify_account_integrity(logistics_acc.id)
    assert r_hold.drift_paise == 0
    assert r_seller.drift_paise == 0
    assert r_logistics.drift_paise == 0


@pytest.mark.asyncio
async def test_illegal_state_transition_rejected(db_session):
    escrow_svc = EscrowService(db_session)
    order = await escrow_svc.create_escrow(
        EscrowCreate(
            order_number="SOLAR-ORD-ILLEGAL-01",
            buyer_id="BUYER-01",
            seller_id="SELLER-01",
            logistics_partner_id="LOGISTICS-01",
            equipment_hsn="8541",
            goods_base_amount_paise=10000000,
            logistics_base_amount_paise=500000,
            seller_gstin="27AAPFU0939F1ZV",
            place_of_supply_state="27",
        )
    )

    # Attempt to jump from CREATED directly to RELEASED
    with pytest.raises(IllegalStateTransitionError) as exc_info:
        await escrow_svc.release_escrow(order.id, triggered_by_user_id="BUYER-01")
    assert "Illegal state transition from 'CREATED' to 'RELEASED'" in str(exc_info.value)

    # Attempt to jump from CREATED directly to IN_TRANSIT
    with pytest.raises(IllegalStateTransitionError):
        await escrow_svc.dispatch_escrow(
            order.id,
            EscrowDispatchRequest(
                seller_user_id="SELLER-01",
                courier_name="BlueDart",
                tracking_number="BD-1122",
            ),
        )


@pytest.mark.asyncio
async def test_dispute_and_admin_resolution_flow(db_session):
    escrow_svc = EscrowService(db_session)
    ledger_svc = LedgerService(db_session)

    order = await escrow_svc.create_escrow(
        EscrowCreate(
            order_number="SOLAR-ORD-DISPUTE-01",
            buyer_id="BUYER-D1",
            seller_id="SELLER-D1",
            logistics_partner_id="LOGISTICS-D1",
            equipment_hsn="8541",
            goods_base_amount_paise=15000000,
            logistics_base_amount_paise=1000000,
            seller_gstin="27AAPFU0939F1ZV",
            place_of_supply_state="27",
        )
    )
    await escrow_svc.fund_escrow(
        order.id,
        EscrowFundRequest(buyer_user_id="BUYER-D1", payment_reference="PAY-D1"),
    )
    await escrow_svc.dispatch_escrow(
        order.id,
        EscrowDispatchRequest(seller_user_id="SELLER-D1", courier_name="DHL", tracking_number="DHL-99"),
    )
    await escrow_svc.deliver_escrow(
        order.id,
        EscrowDeliverRequest(logistics_user_id="LOGISTICS-D1", proof_of_delivery_ref="POD-D1"),
    )

    # Buyer opens dispute
    disputed = await escrow_svc.dispute_escrow(
        order.id,
        EscrowDisputeRequest(
            disputed_by_user_id="BUYER-D1",
            reason="Glass faceplate on 3 solar panels arrived cracked during transit",
        ),
    )
    assert disputed.state == EscrowState.DISPUTED
    assert "cracked" in disputed.dispute_reason

    # Admin resolves dispute in favor of Buyer -> REFUND
    resolved = await escrow_svc.resolve_dispute(
        order.id,
        EscrowResolveRequest(
            admin_user_id="ADMIN-SUPER-01",
            decision=EscrowState.REFUNDED,
            resolution_notes="Carrier inspection confirms transit shock damage. Issuing 100% refund.",
        ),
    )
    assert resolved.state == EscrowState.REFUNDED

    # Check buyer refund account credited
    buyer_acc = await ledger_svc.get_account_by_number(f"PAYABLE-BUYER-REFUND-{order.buyer_id}")
    assert buyer_acc is not None
    assert buyer_acc.balance_paise == order.total_amount_paise

    # Check escrow holding balance is zero
    hold_acc = await ledger_svc.get_account(order.escrow_account_id)
    assert hold_acc.balance_paise == 0
