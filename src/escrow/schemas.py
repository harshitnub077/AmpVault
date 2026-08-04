import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.escrow.models import EscrowState


class EscrowCreate(BaseModel):
    order_number: str = Field(..., min_length=3, max_length=64)
    buyer_id: str = Field(..., min_length=1, max_length=64)
    seller_id: str = Field(..., min_length=1, max_length=64)
    logistics_partner_id: str = Field(..., min_length=1, max_length=64)
    equipment_hsn: str = Field("8541", description="HSN 8541 for solar panels, 8504 for inverters")
    goods_base_amount_paise: int = Field(..., gt=0)
    logistics_base_amount_paise: int = Field(..., gt=0)
    seller_gstin: str = Field(..., min_length=15, max_length=15)
    buyer_gstin: str | None = Field(None, min_length=15, max_length=15)
    place_of_supply_state: str = Field(..., min_length=2, max_length=2)


class EscrowAuditLogResponse(BaseModel):
    id: str
    from_state: EscrowState
    to_state: EscrowState
    triggered_by_user_id: str
    event_type: str
    notes: str | None
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class EscrowResponse(BaseModel):
    id: str
    order_number: str
    buyer_id: str
    seller_id: str
    logistics_partner_id: str
    equipment_hsn: str
    goods_amount_paise: int
    logistics_amount_paise: int
    platform_fee_paise: int
    total_amount_paise: int
    currency: str
    buyer_gstin: str | None
    seller_gstin: str
    place_of_supply_state: str
    state: EscrowState
    escrow_account_id: str
    tracking_number: str | None
    courier_name: str | None
    inspection_deadline: datetime.datetime | None
    dispute_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    audit_logs: list[EscrowAuditLogResponse] = []

    model_config = ConfigDict(from_attributes=True)


class EscrowFundRequest(BaseModel):
    buyer_user_id: str
    payment_reference: str


class EscrowDispatchRequest(BaseModel):
    seller_user_id: str
    courier_name: str
    tracking_number: str


class EscrowDeliverRequest(BaseModel):
    logistics_user_id: str
    proof_of_delivery_ref: str


class EscrowDisputeRequest(BaseModel):
    disputed_by_user_id: str
    reason: str = Field(..., min_length=10, max_length=500)


class EscrowResolveRequest(BaseModel):
    admin_user_id: str
    decision: EscrowState = Field(..., description="Must be RELEASED (favor seller) or REFUNDED (favor buyer)")
    resolution_notes: str = Field(..., min_length=5, max_length=500)
