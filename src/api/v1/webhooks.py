import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.database import get_db
from src.core.exceptions import WebhookVerificationError
from src.escrow.schemas import EscrowDeliverRequest, EscrowFundRequest
from src.escrow.service import EscrowService
from src.webhooks.models import WebhookEvent
from src.webhooks.verifier import verify_webhook_signature

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
settings = get_settings()


@router.post("/gateway")
async def gateway_webhook(
    request: Request,
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    x_webhook_timestamp: str = Header(..., alias="X-Webhook-Timestamp"),
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    try:
        verify_webhook_signature(raw_body, x_webhook_signature, x_webhook_timestamp, settings.GATEWAY_WEBHOOK_SECRET)
    except WebhookVerificationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=e.message)

    payload = json.loads(raw_body)
    event_type = payload.get("event")
    event_id = payload.get("id")

    # Record webhook event
    wh_event = WebhookEvent(
        provider="GATEWAY_MOCK",
        event_id=event_id,
        event_type=event_type,
        payload=raw_body.decode("utf-8"),
        status="PROCESSED",
    )
    db.add(wh_event)

    if event_type == "payment.captured":
        escrow_id = payload["data"]["escrow_id"]
        svc = EscrowService(db)
        await svc.fund_escrow(
            escrow_id,
            EscrowFundRequest(
                buyer_user_id=payload["data"]["buyer_id"],
                payment_reference=event_id,
            ),
        )

    return {"status": "success", "processed_event": event_id}


@router.post("/courier")
async def courier_webhook(
    request: Request,
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    x_webhook_timestamp: str = Header(..., alias="X-Webhook-Timestamp"),
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    try:
        verify_webhook_signature(raw_body, x_webhook_signature, x_webhook_timestamp, settings.COURIER_WEBHOOK_SECRET)
    except WebhookVerificationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=e.message)

    payload = json.loads(raw_body)
    event_type = payload.get("event")
    event_id = payload.get("id")

    wh_event = WebhookEvent(
        provider="COURIER_MOCK",
        event_id=event_id,
        event_type=event_type,
        payload=raw_body.decode("utf-8"),
        status="PROCESSED",
    )
    db.add(wh_event)

    if event_type == "shipment.delivered":
        escrow_id = payload["data"]["escrow_id"]
        svc = EscrowService(db)
        await svc.deliver_escrow(
            escrow_id,
            EscrowDeliverRequest(
                logistics_user_id=payload["data"]["courier_id"],
                proof_of_delivery_ref=payload["data"].get("pod_ref", "MOCK-POD"),
            ),
        )

    return {"status": "success", "processed_event": event_id}
