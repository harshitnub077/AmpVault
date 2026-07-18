from pydantic import BaseModel, ConfigDict, Field


class TaxBreakdown(BaseModel):
    is_interstate: bool = Field(..., description="True if IGST applies, False if CGST+SGST")
    tax_rate_bps: int = Field(..., description="Tax rate in basis points (e.g. 1800 = 18%)")
    base_amount_paise: int
    total_tax_paise: int
    cgst_paise: int = 0
    sgst_paise: int = 0
    igst_paise: int = 0
    total_with_tax_paise: int


class SplitPayoutBreakdown(BaseModel):
    order_amount_paise: int
    goods_tax: TaxBreakdown
    logistics_amount_paise: int
    logistics_tax: TaxBreakdown
    platform_fee_paise: int
    platform_tax: TaxBreakdown
    total_escrow_deposit_paise: int
    seller_net_payout_paise: int
    logistics_net_payout_paise: int
    platform_total_revenue_paise: int

    model_config = ConfigDict(from_attributes=True)
