import asyncio

import fakeredis.aioredis
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.core.exceptions import (
    IdempotencyConflictError,
    IllegalStateTransitionError,
)
from src.core.idempotency import IdempotencyEngine
from src.escrow.models import EscrowState
from src.escrow.schemas import (
    EscrowCreate,
    EscrowDeliverRequest,
    EscrowDispatchRequest,
    EscrowFundRequest,
)
from src.escrow.service import EscrowService
from src.ledger.service import LedgerService


@pytest.mark.asyncio
async def test_100_parallel_release_requests_produce_exactly_one_payout():
    """
    Concurrency Stress Test:
    Spawns 100 parallel coroutines attempting to release the exact same escrow order.
    Guarantees:
    1. Exactly one payout is processed.
    2. Zero double-charges or duplicate journal entries.
    3. Zero balance drift across all participating accounts.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    redis = fakeredis.aioredis.FakeRedis()

    # 1. Setup Escrow in DELIVERED state
    async with session_factory() as setup_session:
        escrow_svc = EscrowService(setup_session)
        order = await escrow_svc.create_escrow(
            EscrowCreate(
                order_number="CONCURRENT-ORD-100",
                buyer_id="BUYER-C100",
                seller_id="SELLER-C100",
                logistics_partner_id="LOGISTICS-C100",
                equipment_hsn="8541",
                goods_base_amount_paise=50000000,  # 5 Lakh INR
                logistics_base_amount_paise=2500000,  # 25,000 INR
                seller_gstin="27AAPFU0939F1ZV",
                place_of_supply_state="27",
            )
        )
        await escrow_svc.fund_escrow(
            order.id,
            EscrowFundRequest(buyer_user_id="BUYER-C100", payment_reference="PAY-C100"),
        )
        await escrow_svc.dispatch_escrow(
            order.id,
            EscrowDispatchRequest(seller_user_id="SELLER-C100", courier_name="BlueDart", tracking_number="BD-100"),
        )
        await escrow_svc.deliver_escrow(
            order.id,
            EscrowDeliverRequest(logistics_user_id="LOGISTICS-C100", proof_of_delivery_ref="POD-100"),
        )
        await setup_session.commit()
        escrow_id = order.id
        seller_id = order.seller_id
        holding_acc_id = order.escrow_account_id
        expected_goods_payout = order.goods_amount_paise

    # 2. Worker logic: attempts to release using IdempotencyEngine protection
    idempotency_key = "IDEMP-CONCURRENCY-RELEASE-KEY-001"
    endpoint = f"/api/v1/escrow/{escrow_id}/release"

    successful_executions = 0
    cached_or_conflict_responses = 0
    lock = asyncio.Lock()

    async def worker_release(worker_id: int):
        nonlocal successful_executions, cached_or_conflict_responses
        async with session_factory() as session:
            idemp = IdempotencyEngine(session, redis_client=redis)
            escrow = EscrowService(session)

            try:
                should_execute, code, body = await idemp.acquire_lock_or_cached_response(
                    key=idempotency_key,
                    endpoint=endpoint,
                    payload={"worker_id": "constant_payload"},
                )

                if should_execute:
                    # Execute the state transition & payout
                    released = await escrow.release_escrow(
                        escrow_id=escrow_id,
                        triggered_by_user_id="BUYER-C100",
                        reason=f"Release executed by worker {worker_id}",
                    )
                    await idemp.save_response(
                        key=idempotency_key,
                        status_code=200,
                        response_body={"status": released.state.value},
                    )
                    await session.commit()
                    async with lock:
                        successful_executions += 1
                else:
                    async with lock:
                        cached_or_conflict_responses += 1

            except (IdempotencyConflictError, IllegalStateTransitionError):
                async with lock:
                    cached_or_conflict_responses += 1
            except Exception:
                # Any other error
                async with lock:
                    cached_or_conflict_responses += 1

    # Launch 100 concurrent workers
    tasks = [worker_release(i) for i in range(100)]
    await asyncio.gather(*tasks)

    # 3. Verify invariants:
    assert successful_executions == 1, f"Expected exactly 1 execution, got {successful_executions}"
    assert (successful_executions + cached_or_conflict_responses) == 100

    # 4. Verify financial balances and zero drift
    async with session_factory() as verify_session:
        ledger = LedgerService(verify_session)
        escrow = EscrowService(verify_session)

        final_order = await escrow.get_escrow_order(escrow_id)
        assert final_order.state == EscrowState.RELEASED

        hold_acc = await ledger.get_account(holding_acc_id)
        assert hold_acc.balance_paise == 0, f"Escrow holding account should be 0, got {hold_acc.balance_paise}"

        seller_acc = await ledger.get_account_by_number(f"PAYABLE-SELLER-{seller_id}")
        assert seller_acc is not None
        assert seller_acc.balance_paise == expected_goods_payout, (
            f"Seller payable should be {expected_goods_payout}, got {seller_acc.balance_paise}"
        )

        # Audit integrity
        rep_hold = await ledger.verify_account_integrity(hold_acc.id)
        rep_seller = await ledger.verify_account_integrity(seller_acc.id)
        assert rep_hold.is_valid is True
        assert rep_hold.drift_paise == 0
        assert rep_seller.is_valid is True
        assert rep_seller.drift_paise == 0

    await engine.dispose()
