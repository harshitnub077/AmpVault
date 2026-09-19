import pytest

from src.adapters.esign_mock import MockSandboxESignProvider
from src.adapters.kyc_mock import MockSandboxKycProvider


@pytest.mark.asyncio
async def test_mock_sandbox_kyc_pan_verification():
    kyc = MockSandboxKycProvider()

    # Valid PAN
    res_valid = await kyc.verify_pan("AAPFU0939F", "Harshit Kudhial")
    assert res_valid.is_verified is True
    assert "MOCK-PAN-VERIFIED" in res_valid.verification_id

    # Invalid regex
    res_invalid = await kyc.verify_pan("INVALIDPAN", "Test Name")
    assert res_invalid.is_verified is False
    assert "format invalid" in res_invalid.message

    # Simulated rejection
    res_rej = await kyc.verify_pan("FAILL1234F", "Rejected Entity")
    assert res_rej.is_verified is False
    assert "rejected" in res_rej.message


@pytest.mark.asyncio
async def test_mock_sandbox_kyc_gstin_verification():
    kyc = MockSandboxKycProvider()

    # Valid GSTIN
    res_valid = await kyc.verify_gstin("27AAPFU0939F1ZV")
    assert res_valid.is_verified is True

    # Invalid GSTIN
    res_invalid = await kyc.verify_gstin("27AAPFU0939F1ZA")
    assert res_invalid.is_verified is False


@pytest.mark.asyncio
async def test_mock_sandbox_esign_tripartite_flow():
    esign = MockSandboxESignProvider()

    # 1. Initiate contract
    doc = await esign.initiate_agreement(
        order_id="ORD-SOLAR-77",
        agreement_title="Tripartite Escrow & Solar Equipment Agreement",
        buyer_id="BUYER-01",
        seller_id="SELLER-01",
        contract_text="Terms: Funds held in Escrowatt escrow until delivery verification.",
    )
    assert doc.document_id is not None
    assert doc.status == "PARTIALLY_SIGNED"  # Platform pre-signs

    # 2. Buyer signs
    doc_after_buyer = await esign.sign_document(doc.document_id, "BUYER", "BUYER-01")
    assert doc_after_buyer.status == "PARTIALLY_SIGNED"

    # 3. Seller signs -> seals agreement
    doc_sealed = await esign.sign_document(doc.document_id, "SELLER", "SELLER-01")
    assert doc_sealed.status == "FULLY_SEALED"
    assert doc_sealed.certificate_url.endswith(".pdf")
