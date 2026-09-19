"""
SANDBOX MOCK ADAPTER - NOT REAL AADHAAR / PAN INTEGRATION
All operations run against deterministic in-memory mock datasets.
Never claims live connection to UIDAI, NSDL, or GST Portal.
"""

import re
import uuid

from src.adapters.interfaces import KycProvider, KycVerificationResult
from src.core.exceptions import GSTValidationError
from src.tax.gst_engine import validate_gstin

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")


class MockSandboxKycProvider(KycProvider):
    """
    Deterministic Sandbox Mock for KYC verification.
    """

    PROVIDER_NAME = "MOCK_SANDBOX_KYC_ADAPTER"

    async def verify_pan(self, pan_number: str, legal_name: str) -> KycVerificationResult:
        pan = pan_number.strip().upper()
        if not PAN_REGEX.match(pan):
            return KycVerificationResult(
                is_verified=False,
                provider=self.PROVIDER_NAME,
                identifier_type="PAN",
                identifier_value=pan,
                verification_id=f"MOCK-PAN-FAIL-{uuid.uuid4().hex[:8]}",
                message="PAN format invalid (expected 5 letters, 4 digits, 1 letter)",
            )

        # Deterministic mock failure on test prefix 'FAILL'
        if pan.startswith("FAILL"):
            return KycVerificationResult(
                is_verified=False,
                provider=self.PROVIDER_NAME,
                identifier_type="PAN",
                identifier_value=pan,
                verification_id=f"MOCK-PAN-REJ-{uuid.uuid4().hex[:8]}",
                message="Sandbox Mock: PAN rejected by simulated verification authority",
            )

        return KycVerificationResult(
            is_verified=True,
            provider=self.PROVIDER_NAME,
            identifier_type="PAN",
            identifier_value=pan,
            entity_name=legal_name,
            verification_id=f"MOCK-PAN-VERIFIED-{uuid.uuid4().hex[:8]}",
            message="Sandbox Mock: PAN verified successfully against simulated NSDL database",
        )

    async def verify_gstin(self, gstin: str) -> KycVerificationResult:
        try:
            validate_gstin(gstin)
            return KycVerificationResult(
                is_verified=True,
                provider=self.PROVIDER_NAME,
                identifier_type="GSTIN",
                identifier_value=gstin.upper(),
                verification_id=f"MOCK-GSTIN-VERIFIED-{uuid.uuid4().hex[:8]}",
                message="Sandbox Mock: GSTIN format and check digit mathematically validated",
            )
        except GSTValidationError as e:
            return KycVerificationResult(
                is_verified=False,
                provider=self.PROVIDER_NAME,
                identifier_type="GSTIN",
                identifier_value=gstin,
                verification_id=f"MOCK-GSTIN-FAIL-{uuid.uuid4().hex[:8]}",
                message=str(e),
            )
