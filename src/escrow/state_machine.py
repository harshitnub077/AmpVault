from src.core.exceptions import IllegalStateTransitionError
from src.escrow.models import EscrowState

# Explicit Directed Acyclic Graph (with dispute loops) for Escrow Lifecycle
ALLOWED_TRANSITIONS: dict[EscrowState, set[EscrowState]] = {
    EscrowState.CREATED: {EscrowState.FUNDED},
    EscrowState.FUNDED: {EscrowState.IN_TRANSIT, EscrowState.REFUNDED},
    EscrowState.IN_TRANSIT: {EscrowState.DELIVERED, EscrowState.DISPUTED},
    EscrowState.DELIVERED: {EscrowState.RELEASED, EscrowState.DISPUTED},
    EscrowState.DISPUTED: {EscrowState.RELEASED, EscrowState.REFUNDED},
    EscrowState.RELEASED: set(),  # Terminal state
    EscrowState.REFUNDED: set(),  # Terminal state
}


def validate_transition(current_state: EscrowState, next_state: EscrowState) -> None:
    """
    Validate that a proposed state transition is legally permitted.
    Raises IllegalStateTransitionError with detailed explanation on violation.
    """
    if current_state == next_state:
        raise IllegalStateTransitionError(f"Escrow order is already in state '{current_state.value}'")

    allowed_targets = ALLOWED_TRANSITIONS.get(current_state, set())
    if next_state not in allowed_targets:
        allowed_str = ", ".join(f"'{s.value}'" for s in allowed_targets) or "None (Terminal State)"
        raise IllegalStateTransitionError(
            f"Illegal state transition from '{current_state.value}' to '{next_state.value}'. "
            f"Allowed next states from '{current_state.value}' are: [{allowed_str}]."
        )
