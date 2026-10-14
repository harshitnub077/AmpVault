from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import AccountNotFoundError
from src.ledger.models import Account
from src.ledger.schemas import AccountIntegrityReport, AccountResponse
from src.ledger.service import LedgerService

router = APIRouter(prefix="/ledger", tags=["Ledger"])


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    stmt = select(Account).order_by(Account.created_at.desc()).limit(100)
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/accounts/{account_id}/integrity", response_model=AccountIntegrityReport)
async def audit_account_integrity(account_id: str, db: AsyncSession = Depends(get_db)):
    service = LedgerService(db)
    try:
        return await service.verify_account_integrity(account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
