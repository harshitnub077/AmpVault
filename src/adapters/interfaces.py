from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class KycVerificationResult(BaseModel):
    is_verified: bool
    provider: str
    identifier_type: str  # PAN, GSTIN, AADHAAR_MOCK
    identifier_value: str
    entity_name: str | None = None
    verification_id: str
    message: str


class ESignDocumentResult(BaseModel):
    document_id: str
    agreement_title: str
    document_hash: str
    status: str  # DRAFT, PARTIALLY_SIGNED, FULLY_SEALED
    signers: list[dict]
    certificate_url: str


@runtime_checkable
class KycProvider(Protocol):
    """Port interface for Identity & Compliance Verification."""

    async def verify_pan(self, pan_number: str, legal_name: str) -> KycVerificationResult: ...

    async def verify_gstin(self, gstin: str) -> KycVerificationResult: ...


@runtime_checkable
class ESignProvider(Protocol):
    """Port interface for Tripartite Escrow Agreement e-Signing."""

    async def initiate_agreement(
        self, order_id: str, agreement_title: str, buyer_id: str, seller_id: str, contract_text: str
    ) -> ESignDocumentResult: ...

    async def sign_document(self, document_id: str, signer_role: str, signer_id: str) -> ESignDocumentResult: ...
