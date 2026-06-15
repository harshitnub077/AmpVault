from typing import Any


class EscrowattException(Exception):
    """Base class for all domain exceptions in Escrowatt."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LedgerUnbalancedError(EscrowattException):
    """Raised when sum of debits does not equal sum of credits in a journal entry."""

    pass


class InvalidAmountError(EscrowattException):
    """Raised when amount is zero, negative, or not an integer paise value."""

    pass


class AccountNotFoundError(EscrowattException):
    """Raised when referenced ledger account does not exist."""

    pass


class IllegalStateTransitionError(EscrowattException):
    """Raised when an invalid state transition is attempted on an escrow order."""

    pass


class EscrowNotFoundError(EscrowattException):
    """Raised when requested escrow order is not found."""

    pass


class IdempotencyConflictError(EscrowattException):
    """Raised when an operation with the same idempotency key is currently processing."""

    pass


class IdempotencyPayloadMismatchError(EscrowattException):
    """Raised when the same idempotency key is reused with a different request payload."""

    pass


class GSTValidationError(EscrowattException):
    """Raised when GSTIN format or checksum validation fails."""

    pass


class DisputeResolutionError(EscrowattException):
    """Raised when dispute resolution violates escrow business rules."""

    pass


class UnauthorizedError(EscrowattException):
    """Raised when user lacks required role or permissions."""

    pass


class WebhookVerificationError(EscrowattException):
    """Raised when webhook signature verification or timestamp drift check fails."""

    pass
