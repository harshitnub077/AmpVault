import json
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.exceptions import (
    EscrowNotFoundError,
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
    IllegalStateTransitionError,
)
from src.core.idempotency import IdempotencyEngine
from src.escrow.schemas import (
    EscrowCreate,
    EscrowDeliverRequest,
    EscrowDispatchRequest,
    EscrowDisputeRequest,
    EscrowFundRequest,
    EscrowResponse,
)
from src.escrow.service import EscrowService

router = APIRouter(prefix="/escrow", tags=["Escrow Orders"])


@router.post("", response_model=EscrowResponse, status_code=status.HTTP_201_CREATED)
async def create_escrow_order(
    data: EscrowCreate,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    try:
        order = await service.create_escrow(data)
        return order
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{escrow_id}", response_model=EscrowResponse)
async def get_escrow_order(
    escrow_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    try:
        return await service.get_escrow_order(escrow_id)
    except EscrowNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)


@router.post("/{escrow_id}/fund", response_model=EscrowResponse)
async def fund_escrow_order(
    escrow_id: str,
    data: EscrowFundRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    idemp = IdempotencyEngine(db)

    endpoint = f"/api/v1/escrow/{escrow_id}/fund"
    if idempotency_key:
        try:
            should_run, code, body = await idemp.acquire_lock_or_cached_response(
                idempotency_key, endpoint, data.model_dump()
            )
            if not should_run:
                if body is not None:
                    return json.loads(body)
                raise HTTPException(status_code=status.HTTP_200_OK, detail="Processed")
        except IdempotencyConflictError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message)
        except IdempotencyPayloadMismatchError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.message)

    try:
        order = await service.fund_escrow(escrow_id, data)
        resp_model = EscrowResponse.model_validate(order)
        if idempotency_key:
            await idemp.save_response(idempotency_key, 200, resp_model.model_dump(mode="json"))
        return resp_model
    except IllegalStateTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except EscrowNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)


@router.post("/{escrow_id}/dispatch", response_model=EscrowResponse)
async def dispatch_escrow_order(
    escrow_id: str,
    data: EscrowDispatchRequest,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    try:
        return await service.dispatch_escrow(escrow_id, data)
    except (IllegalStateTransitionError, EscrowNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post("/{escrow_id}/deliver", response_model=EscrowResponse)
async def deliver_escrow_order(
    escrow_id: str,
    data: EscrowDeliverRequest,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    try:
        return await service.deliver_escrow(escrow_id, data)
    except (IllegalStateTransitionError, EscrowNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post("/{escrow_id}/release", response_model=EscrowResponse)
async def release_escrow_order(
    escrow_id: str,
    triggered_by_user_id: str,
    reason: str = "Buyer approved release",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    idemp = IdempotencyEngine(db)

    endpoint = f"/api/v1/escrow/{escrow_id}/release"
    payload = {"triggered_by": triggered_by_user_id, "reason": reason}

    if idempotency_key:
        try:
            should_run, code, body = await idemp.acquire_lock_or_cached_response(idempotency_key, endpoint, payload)
            if not should_run:
                if body is not None:
                    return json.loads(body)
                raise HTTPException(status_code=status.HTTP_200_OK, detail="Processed")
        except IdempotencyConflictError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message)
        except IdempotencyPayloadMismatchError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.message)

    try:
        order = await service.release_escrow(escrow_id, triggered_by_user_id, reason)
        resp_model = EscrowResponse.model_validate(order)
        if idempotency_key:
            await idemp.save_response(idempotency_key, 200, resp_model.model_dump(mode="json"))
        return resp_model
    except (IllegalStateTransitionError, EscrowNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post("/{escrow_id}/refund", response_model=EscrowResponse)
async def refund_escrow_order(
    escrow_id: str,
    triggered_by_user_id: str,
    reason: str,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    idemp = IdempotencyEngine(db)

    endpoint = f"/api/v1/escrow/{escrow_id}/refund"
    payload = {"triggered_by": triggered_by_user_id, "reason": reason}

    if idempotency_key:
        try:
            should_run, code, body = await idemp.acquire_lock_or_cached_response(idempotency_key, endpoint, payload)
            if not should_run:
                if body is not None:
                    return json.loads(body)
                raise HTTPException(status_code=status.HTTP_200_OK, detail="Processed")
        except IdempotencyConflictError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.message)
        except IdempotencyPayloadMismatchError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.message)

    try:
        order = await service.refund_escrow(escrow_id, triggered_by_user_id, reason)
        resp_model = EscrowResponse.model_validate(order)
        if idempotency_key:
            await idemp.save_response(idempotency_key, 200, resp_model.model_dump(mode="json"))
        return resp_model
    except (IllegalStateTransitionError, EscrowNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post("/{escrow_id}/dispute", response_model=EscrowResponse)
async def dispute_escrow_order(
    escrow_id: str,
    data: EscrowDisputeRequest,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    try:
        return await service.dispute_escrow(escrow_id, data)
    except (IllegalStateTransitionError, EscrowNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
