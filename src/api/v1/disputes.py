from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import DisputeResolutionError, EscrowNotFoundError
from src.escrow.schemas import EscrowResolveRequest, EscrowResponse
from src.escrow.service import EscrowService

router = APIRouter(prefix="/disputes", tags=["Dispute Resolution"])


@router.post("/{escrow_id}/resolve", response_model=EscrowResponse)
async def resolve_dispute(
    escrow_id: str,
    data: EscrowResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    service = EscrowService(db)
    try:
        return await service.resolve_dispute(escrow_id, data)
    except (DisputeResolutionError, EscrowNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
