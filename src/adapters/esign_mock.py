"""
SANDBOX MOCK ADAPTER - NOT REAL ESP / AADHAAR E-SIGN
Simulates legal document hashing and multi-party tripartite signature flows.
"""

import datetime
import hashlib
import uuid

from src.adapters.interfaces import ESignDocumentResult, ESignProvider


class MockSandboxESignProvider(ESignProvider):
    """
    Deterministic Sandbox Mock for Tripartite Solar Escrow Agreement e-Sign.
    Tracks signing status across Buyer, Seller, and Escrowatt Platform.
    """

    PROVIDER_NAME = "MOCK_SANDBOX_ESIGN_ADAPTER"

    def __init__(self) -> None:
        self._agreements: dict[str, dict] = {}

    async def initiate_agreement(
        self, order_id: str, agreement_title: str, buyer_id: str, seller_id: str, contract_text: str
    ) -> ESignDocumentResult:
        doc_id = str(uuid.uuid4())
        doc_hash = hashlib.sha256(contract_text.encode("utf-8")).hexdigest()

        signers = [
            {"role": "BUYER", "id": buyer_id, "signed": False, "signed_at": None},
            {"role": "SELLER", "id": seller_id, "signed": False, "signed_at": None},
            {
                "role": "PLATFORM",
                "id": "ESCROWATT_PLATFORM",
                "signed": True,
                "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        ]

        self._agreements[doc_id] = {
            "document_id": doc_id,
            "order_id": order_id,
            "title": agreement_title,
            "hash": doc_hash,
            "status": "PARTIALLY_SIGNED",
            "signers": signers,
            "certificate_url": f"https://sandbox.escrowatt.internal/certs/{doc_id}.pdf",
        }

        return self._build_result(doc_id)

    async def sign_document(self, document_id: str, signer_role: str, signer_id: str) -> ESignDocumentResult:
        if document_id not in self._agreements:
            raise ValueError(f"Agreement document '{document_id}' not found in mock store")

        doc = self._agreements[document_id]
        updated = False
        for s in doc["signers"]:
            if s["role"] == signer_role and s["id"] == signer_id:
                s["signed"] = True
                s["signed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                updated = True
                break

        if not updated:
            raise ValueError(f"Signer {signer_role}:{signer_id} not authorized for this document")

        all_signed = all(s["signed"] for s in doc["signers"])
        if all_signed:
            doc["status"] = "FULLY_SEALED"

        return self._build_result(document_id)

    def _build_result(self, document_id: str) -> ESignDocumentResult:
        d = self._agreements[document_id]
        return ESignDocumentResult(
            document_id=d["document_id"],
            agreement_title=d["title"],
            document_hash=d["hash"],
            status=d["status"],
            signers=d["signers"],
            certificate_url=d["certificate_url"],
        )
