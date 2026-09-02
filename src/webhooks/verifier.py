import hashlib
import hmac
import time

from src.core.exceptions import WebhookVerificationError


def sign_payload(payload_bytes: bytes, secret: str, timestamp: int) -> str:
    """Generate HMAC-SHA256 signature for payload with timestamp."""
    signed_data = f"{timestamp}.".encode() + payload_bytes
    return hmac.new(secret.encode("utf-8"), signed_data, hashlib.sha256).hexdigest()


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: str,
    timestamp_header: str,
    secret: str,
    max_drift_seconds: int = 300,
) -> bool:
    """
    Verify incoming webhook:
    1. Timestamp drift defense (mitigates replay attacks within 300s window).
    2. Constant-time HMAC-SHA256 comparison.
    """
    try:
        timestamp = int(timestamp_header)
    except (ValueError, TypeError):
        raise WebhookVerificationError("Invalid or missing X-Webhook-Timestamp header")

    current_time = int(time.time())
    if abs(current_time - timestamp) > max_drift_seconds:
        raise WebhookVerificationError(
            f"Webhook timestamp drifted by {abs(current_time - timestamp)}s (allowed: {max_drift_seconds}s)"
        )

    expected_sig = sign_payload(raw_body, secret, timestamp)
    if not hmac.compare_digest(signature_header, expected_sig):
        raise WebhookVerificationError("Webhook HMAC signature mismatch")

    return True
