from src.core.exceptions import InvalidAmountError
from src.tax.gst_engine import get_hsn_tax_rate_bps, validate_gstin
from src.tax.schemas import SplitPayoutBreakdown, TaxBreakdown


def calculate_tax_breakdown(
    base_amount_paise: int,
    hsn_code: str,
    supplier_state_code: str,
    place_of_supply_state_code: str,
) -> TaxBreakdown:
    """
    Calculate statutory GST breakdown in integer paise:
    - Intra-state (Supplier State == Place of Supply): CGST (50%) + SGST (50%).
    - Inter-state (Supplier State != Place of Supply): IGST (100%).
    Enforces half-up rounding in paise and guarantees: CGST + SGST == Total Tax.
    """
    if base_amount_paise <= 0:
        raise InvalidAmountError(f"Base amount must be positive, got {base_amount_paise}")

    tax_rate_bps = get_hsn_tax_rate_bps(hsn_code)
    # Integer paise tax calculation: (base * bps + 5000) // 10000 (half-up)
    total_tax_paise = (base_amount_paise * tax_rate_bps + 5000) // 10000

    is_interstate = supplier_state_code != place_of_supply_state_code

    if is_interstate:
        return TaxBreakdown(
            is_interstate=True,
            tax_rate_bps=tax_rate_bps,
            base_amount_paise=base_amount_paise,
            total_tax_paise=total_tax_paise,
            cgst_paise=0,
            sgst_paise=0,
            igst_paise=total_tax_paise,
            total_with_tax_paise=base_amount_paise + total_tax_paise,
        )
    else:
        # Half-up rounding for CGST, SGST takes the remainder
        cgst_paise = (total_tax_paise + 1) // 2
        sgst_paise = total_tax_paise - cgst_paise
        return TaxBreakdown(
            is_interstate=False,
            tax_rate_bps=tax_rate_bps,
            base_amount_paise=base_amount_paise,
            total_tax_paise=total_tax_paise,
            cgst_paise=cgst_paise,
            sgst_paise=sgst_paise,
            igst_paise=0,
            total_with_tax_paise=base_amount_paise + total_tax_paise,
        )


def compute_escrow_split_payout(
    goods_base_amount_paise: int,
    equipment_hsn: str,
    seller_gstin: str,
    place_of_supply_state_code: str,
    logistics_base_amount_paise: int,
    platform_fee_bps: int = 150,  # 1.5%
    platform_state_code: str = "27",  # Maharashtra HQ
) -> SplitPayoutBreakdown:
    """
    Compute split payouts for Buyer, Seller, Logistics, and Platform with GST:
    - Goods: HSN 8541 (12%) or HSN 8504 (18%)
    - Logistics: HSN 9965 (18%)
    - Platform Fee: HSN 9983 (18%)
    """
    validate_gstin(seller_gstin)
    seller_state_code = seller_gstin[:2]

    goods_tax = calculate_tax_breakdown(
        base_amount_paise=goods_base_amount_paise,
        hsn_code=equipment_hsn,
        supplier_state_code=seller_state_code,
        place_of_supply_state_code=place_of_supply_state_code,
    )

    logistics_tax = calculate_tax_breakdown(
        base_amount_paise=logistics_base_amount_paise,
        hsn_code="9965",
        supplier_state_code=seller_state_code,  # Logistics billed from dispatch state
        place_of_supply_state_code=place_of_supply_state_code,
    )

    platform_base_fee_paise = (goods_base_amount_paise * platform_fee_bps + 5000) // 10000
    platform_tax = calculate_tax_breakdown(
        base_amount_paise=platform_base_fee_paise,
        hsn_code="9983",
        supplier_state_code=platform_state_code,
        place_of_supply_state_code=place_of_supply_state_code,
    )

    total_escrow_deposit_paise = (
        goods_tax.total_with_tax_paise + logistics_tax.total_with_tax_paise + platform_tax.total_with_tax_paise
    )

    seller_net_payout_paise = goods_tax.total_with_tax_paise
    logistics_net_payout_paise = logistics_tax.total_with_tax_paise
    platform_total_revenue_paise = platform_tax.total_with_tax_paise

    return SplitPayoutBreakdown(
        order_amount_paise=goods_tax.total_with_tax_paise,
        goods_tax=goods_tax,
        logistics_amount_paise=logistics_tax.total_with_tax_paise,
        logistics_tax=logistics_tax,
        platform_fee_paise=platform_tax.total_with_tax_paise,
        platform_tax=platform_tax,
        total_escrow_deposit_paise=total_escrow_deposit_paise,
        seller_net_payout_paise=seller_net_payout_paise,
        logistics_net_payout_paise=logistics_net_payout_paise,
        platform_total_revenue_paise=platform_total_revenue_paise,
    )
