import pytest

from src.core.exceptions import GSTValidationError
from src.tax.gst_engine import (
    get_hsn_tax_rate_bps,
    validate_gstin,
)
from src.tax.split_calculator import (
    calculate_tax_breakdown,
    compute_escrow_split_payout,
)


def test_valid_gstin():
    assert validate_gstin("27AAPFU0939F1ZV") is True
    assert validate_gstin("29ABCDE1234F1ZW") is True
    assert validate_gstin("07AAAAA0000A1Z4") is True


def test_invalid_gstin_length_and_regex():
    with pytest.raises(GSTValidationError):
        validate_gstin("27AAPFU0939F1Z")  # 14 chars

    with pytest.raises(GSTValidationError):
        validate_gstin("INVALIDGSTIN123")


def test_invalid_state_code():
    # 99 is invalid state code
    with pytest.raises(GSTValidationError) as exc:
        validate_gstin("99AAPFU0939F1ZV")
    assert "Invalid state code" in str(exc.value)


def test_invalid_check_digit():
    # Corrupt the check digit from 'V' to 'A'
    with pytest.raises(GSTValidationError) as exc:
        validate_gstin("27AAPFU0939F1ZA")
    assert "check-digit mismatch" in str(exc.value)


def test_hsn_rates():
    assert get_hsn_tax_rate_bps("8541") == 1200  # 12%
    assert get_hsn_tax_rate_bps("8504") == 1800  # 18%
    assert get_hsn_tax_rate_bps("9965") == 1800  # 18%
    assert get_hsn_tax_rate_bps("9983") == 1800  # 18%

    with pytest.raises(GSTValidationError):
        get_hsn_tax_rate_bps("0000")


def test_intra_state_tax_breakdown():
    # Intra-state: Supplier State '27' == Place of Supply '27'
    # Base: ₹1,00,000 (10,000,000 paise), HSN 8541 (12%) -> Tax: ₹12,000 (1,200,000 paise)
    # CGST (6%) = ₹6,000 (600,000 paise), SGST (6%) = ₹6,000 (600,000 paise)
    tb = calculate_tax_breakdown(
        base_amount_paise=10000000,
        hsn_code="8541",
        supplier_state_code="27",
        place_of_supply_state_code="27",
    )
    assert tb.is_interstate is False
    assert tb.tax_rate_bps == 1200
    assert tb.total_tax_paise == 1200000
    assert tb.cgst_paise == 600000
    assert tb.sgst_paise == 600000
    assert tb.igst_paise == 0
    assert tb.cgst_paise + tb.sgst_paise == tb.total_tax_paise
    assert tb.total_with_tax_paise == 11200000


def test_inter_state_tax_breakdown():
    # Inter-state: Supplier State '27' (MH) != Place of Supply '29' (KA)
    # Base: ₹1,00,000 (10,000,000 paise), HSN 8504 (18%) -> Tax: ₹18,000 (1,800,000 paise)
    # IGST (18%) = 1,800,000 paise, CGST = 0, SGST = 0
    tb = calculate_tax_breakdown(
        base_amount_paise=10000000,
        hsn_code="8504",
        supplier_state_code="27",
        place_of_supply_state_code="29",
    )
    assert tb.is_interstate is True
    assert tb.total_tax_paise == 1800000
    assert tb.igst_paise == 1800000
    assert tb.cgst_paise == 0
    assert tb.sgst_paise == 0
    assert tb.total_with_tax_paise == 11800000


def test_split_payout_computation():
    split = compute_escrow_split_payout(
        goods_base_amount_paise=10000000,  # 1 Lakh INR (HSN 8541 12%) -> 1,12,000 with tax
        equipment_hsn="8541",
        seller_gstin="27AAPFU0939F1ZV",
        place_of_supply_state_code="27",
        logistics_base_amount_paise=500000,  # 5,000 INR (HSN 9965 18%) -> 5,900 with tax
        platform_fee_bps=150,  # 1.5% of 10000000 = 150000 (HSN 9983 18%) -> 1,770 with tax
    )

    assert split.order_amount_paise == 11200000
    assert split.logistics_amount_paise == 590000
    assert split.platform_fee_paise == 177000
    assert split.total_escrow_deposit_paise == 11200000 + 590000 + 177000
    assert split.seller_net_payout_paise == split.order_amount_paise
