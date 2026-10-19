import json
import time
import uuid

import httpx
import pytest

from src.core.config import get_settings
from src.core.database import Base, engine
from src.main import app
from src.webhooks.verifier import sign_payload

settings = get_settings()


@pytest.fixture(autouse=True)
async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_health_and_metrics_endpoints():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Liveness
        live = await client.get("/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "alive"

        # Readiness
        ready = await client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        # Metrics
        met = await client.get("/metrics")
        assert met.status_code == 200
        assert "http_requests_total" in met.text


@pytest.mark.asyncio
async def test_full_api_escrow_workflow():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Register User
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "buyer.integration@example.com",
                "password": "Password123!",
                "role": "BUYER",
                "full_name": "Solar Buyer",
            },
        )
        assert reg.status_code == 201

        # 2. Login
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "buyer.integration@example.com", "password": "Password123!"},
        )
        assert login.status_code == 200
        tokens = login.json()
        assert "access_token" in tokens

        # 3. Create Escrow Order
        order_payload = {
            "order_number": f"API-SOLAR-ORD-{uuid.uuid4().hex[:6]}",
            "buyer_id": "BUYER-INT-01",
            "seller_id": "SELLER-INT-01",
            "logistics_partner_id": "LOGISTICS-INT-01",
            "equipment_hsn": "8541",
            "goods_base_amount_paise": 10000000,  # 1 Lakh INR
            "logistics_base_amount_paise": 500000,  # 5,000 INR
            "seller_gstin": "27AAPFU0939F1ZV",
            "place_of_supply_state": "27",
        }
        res_create = await client.post("/api/v1/escrow", json=order_payload)
        assert res_create.status_code == 201, f"Failed create: {res_create.text}"
        order = res_create.json()
        escrow_id = order["id"]
        assert order["state"] == "CREATED"
        assert order["total_amount_paise"] > 0

        # Fetch by ID
        fetch_res = await client.get(f"/api/v1/escrow/{escrow_id}")
        assert fetch_res.status_code == 200
        assert fetch_res.json()["id"] == escrow_id

        # 4. Fund Order with Idempotency Key
        fund_key = f"IDEMP-FUND-KEY-{uuid.uuid4().hex[:6]}"
        fund_payload = {
            "buyer_user_id": "BUYER-INT-01",
            "payment_reference": "PG-REF-101",
        }
        res_fund = await client.post(
            f"/api/v1/escrow/{escrow_id}/fund",
            json=fund_payload,
            headers={"Idempotency-Key": fund_key},
        )
        assert res_fund.status_code == 200
        assert res_fund.json()["state"] == "FUNDED"

        # 5. Retry Fund with identical Idempotency Key -> returns cached response without duplicate funding
        res_fund_retry = await client.post(
            f"/api/v1/escrow/{escrow_id}/fund",
            json=fund_payload,
            headers={"Idempotency-Key": fund_key},
        )
        assert res_fund_retry.status_code == 200
        assert res_fund_retry.json()["state"] == "FUNDED"

        # 6. Dispatch Goods
        res_dispatch = await client.post(
            f"/api/v1/escrow/{escrow_id}/dispatch",
            json={
                "seller_user_id": "SELLER-INT-01",
                "courier_name": "Delhivery",
                "tracking_number": "DEL-101",
            },
        )
        assert res_dispatch.status_code == 200
        assert res_dispatch.json()["state"] == "IN_TRANSIT"

        # 7. Deliver Goods
        res_deliver = await client.post(
            f"/api/v1/escrow/{escrow_id}/deliver",
            json={
                "logistics_user_id": "LOGISTICS-INT-01",
                "proof_of_delivery_ref": "POD-INT-101",
            },
        )
        assert res_deliver.status_code == 200
        assert res_deliver.json()["state"] == "DELIVERED"

        # 8. Release Escrow with Idempotency Key
        release_key = f"IDEMP-RELEASE-KEY-{uuid.uuid4().hex[:6]}"
        res_release = await client.post(
            f"/api/v1/escrow/{escrow_id}/release?triggered_by_user_id=BUYER-INT-01&reason=Goods_verified",
            headers={"Idempotency-Key": release_key},
        )
        assert res_release.status_code == 200
        assert res_release.json()["state"] == "RELEASED"

        # 9. List accounts & audit account integrity
        acc_list = await client.get("/api/v1/ledger/accounts")
        assert acc_list.status_code == 200
        assert len(acc_list.json()) > 0

        acc_res = await client.get(f"/api/v1/ledger/accounts/{order['escrow_account_id']}/integrity")
        assert acc_res.status_code == 200
        report = acc_res.json()
        assert report["is_valid"] is True
        assert report["drift_paise"] == 0
        assert report["cached_balance_paise"] == 0


@pytest.mark.asyncio
async def test_webhook_payment_captured_and_courier_endpoints():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create an escrow order
        create_resp = await client.post(
            "/api/v1/escrow",
            json={
                "order_number": f"WH-ORD-{uuid.uuid4().hex[:6]}",
                "buyer_id": "BUYER-WH",
                "seller_id": "SELLER-WH",
                "logistics_partner_id": "LOGISTICS-WH",
                "goods_base_amount_paise": 5000000,
                "logistics_base_amount_paise": 200000,
                "seller_gstin": "27AAPFU0939F1ZV",
                "place_of_supply_state": "27",
            },
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        escrow_id = create_resp.json()["id"]

        # 1. Gateway Webhook (payment.captured)
        gw_body = json.dumps(
            {
                "id": f"evt_gw_{uuid.uuid4().hex[:6]}",
                "event": "payment.captured",
                "data": {"escrow_id": escrow_id, "buyer_id": "BUYER-WH"},
            }
        ).encode("utf-8")
        ts = int(time.time())
        sig = sign_payload(gw_body, settings.GATEWAY_WEBHOOK_SECRET, ts)

        gw_resp = await client.post(
            "/api/v1/webhooks/gateway",
            content=gw_body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": sig,
                "X-Webhook-Timestamp": str(ts),
            },
        )
        assert gw_resp.status_code == 200
        assert gw_resp.json()["status"] == "success"

        # Check order is now FUNDED
        order_get = await client.get(f"/api/v1/escrow/{escrow_id}")
        assert order_get.json()["state"] == "FUNDED"

        # Dispatch order so it's IN_TRANSIT
        await client.post(
            f"/api/v1/escrow/{escrow_id}/dispatch",
            json={
                "seller_user_id": "SELLER-WH",
                "courier_name": "Shiprocket",
                "tracking_number": "SR-999",
            },
        )

        # 2. Courier Webhook (shipment.delivered)
        courier_body = json.dumps(
            {
                "id": f"evt_courier_{uuid.uuid4().hex[:6]}",
                "event": "shipment.delivered",
                "data": {"escrow_id": escrow_id, "courier_id": "LOGISTICS-WH", "pod_ref": "POD-888"},
            }
        ).encode("utf-8")
        ts_courier = int(time.time())
        sig_courier = sign_payload(courier_body, settings.COURIER_WEBHOOK_SECRET, ts_courier)

        courier_resp = await client.post(
            "/api/v1/webhooks/courier",
            content=courier_body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": sig_courier,
                "X-Webhook-Timestamp": str(ts_courier),
            },
        )
        assert courier_resp.status_code == 200
        assert courier_resp.json()["status"] == "success"

        # Check order is now DELIVERED
        final_get = await client.get(f"/api/v1/escrow/{escrow_id}")
        assert final_get.json()["state"] == "DELIVERED"


@pytest.mark.asyncio
async def test_dispute_and_resolve_api():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create, fund, dispatch, deliver
        create_resp = await client.post(
            "/api/v1/escrow",
            json={
                "order_number": f"DISP-ORD-{uuid.uuid4().hex[:6]}",
                "buyer_id": "BUYER-DISP",
                "seller_id": "SELLER-DISP",
                "logistics_partner_id": "LOGISTICS-DISP",
                "goods_base_amount_paise": 6000000,
                "logistics_base_amount_paise": 300000,
                "seller_gstin": "27AAPFU0939F1ZV",
                "place_of_supply_state": "27",
            },
        )
        escrow_id = create_resp.json()["id"]

        await client.post(
            f"/api/v1/escrow/{escrow_id}/fund",
            json={"buyer_user_id": "BUYER-DISP", "payment_reference": "REF-DISP"},
        )
        await client.post(
            f"/api/v1/escrow/{escrow_id}/dispatch",
            json={"seller_user_id": "SELLER-DISP", "courier_name": "DHL", "tracking_number": "TRK-DISP"},
        )
        await client.post(
            f"/api/v1/escrow/{escrow_id}/deliver",
            json={"logistics_user_id": "LOGISTICS-DISP", "proof_of_delivery_ref": "POD-DISP"},
        )

        # Open dispute
        disp_resp = await client.post(
            f"/api/v1/escrow/{escrow_id}/dispute",
            json={"disputed_by_user_id": "BUYER-DISP", "reason": "Severe physical damage during shipping"},
        )
        assert disp_resp.status_code == 200
        assert disp_resp.json()["state"] == "DISPUTED"

        # Admin resolves dispute -> REFUND
        resolve_resp = await client.post(
            f"/api/v1/disputes/{escrow_id}/resolve",
            json={
                "admin_user_id": "ADMIN-SUPER",
                "decision": "REFUNDED",
                "resolution_notes": "Damaged in transit, carrier insurance claimed.",
            },
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["state"] == "REFUNDED"


@pytest.mark.asyncio
async def test_reconciliation_api_endpoint():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        rec_resp = await client.post(
            "/api/v1/reconciliation/run",
            json=[],
        )
        assert rec_resp.status_code == 200
        report = rec_resp.json()
        assert report["is_balanced"] is True
