import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.ledger.models import AccountType, JournalEntryStatus, PostingDirection


class AccountCreate(BaseModel):
    account_number: str = Field(..., min_length=3, max_length=64)
    name: str = Field(..., min_length=2, max_length=255)
    type: AccountType
    currency: str = Field("INR", min_length=3, max_length=3)


class AccountResponse(BaseModel):
    id: str
    account_number: str
    name: str
    type: AccountType
    currency: str
    balance_paise: int
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class PostingCreate(BaseModel):
    account_id: str
    direction: PostingDirection
    amount_paise: int = Field(..., gt=0, description="Positive integer amount in paise")


class PostingResponse(BaseModel):
    id: str
    journal_entry_id: str
    account_id: str
    direction: PostingDirection
    amount_paise: int
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class JournalEntryCreate(BaseModel):
    description: str = Field(..., min_length=3, max_length=512)
    reference_type: str = Field(..., min_length=2, max_length=64)
    reference_id: str = Field(..., min_length=1, max_length=128)
    postings: list[PostingCreate] = Field(..., min_length=2)


class JournalEntryResponse(BaseModel):
    id: str
    description: str
    reference_type: str
    reference_id: str
    status: JournalEntryStatus
    posted_at: datetime.datetime
    postings: list[PostingResponse]

    model_config = ConfigDict(from_attributes=True)


class AccountIntegrityReport(BaseModel):
    account_id: str
    account_number: str
    cached_balance_paise: int
    calculated_balance_paise: int
    drift_paise: int
    is_valid: bool
