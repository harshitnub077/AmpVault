from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.reconciliation.engine import (
    DriftReport,
    GatewayPaymentRecord,
    ReconciliationEngine,
)

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.post("/run", response_model=DriftReport)
async def run_reconciliation(
    gateway_records: list[GatewayPaymentRecord],
    db: AsyncSession = Depends(get_db),
):
    engine = ReconciliationEngine(db)
    return await engine.run_reconciliation(gateway_records)
