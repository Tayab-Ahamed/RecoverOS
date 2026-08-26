"""Safe error shaping.

Clients receive a stable code and a safe message. Stack traces and internal
detail are logged, never returned.
"""

from __future__ import annotations

from app.domain.errors import (
    DomainError,
    IllegalTransition,
    InvariantViolation,
    MissingProviderEventId,
    MoneyError,
    PolicyViolation,
    UnauthorizedActor,
)

STATUS_MAP: dict[type[Exception], tuple[int, str]] = {
    PolicyViolation: (403, "policy_violation"),
    UnauthorizedActor: (403, "unauthorized_actor"),
    IllegalTransition: (409, "illegal_transition"),
    InvariantViolation: (500, "invariant_violation"),
    MoneyError: (400, "invalid_amount"),
    MissingProviderEventId: (400, "malformed_webhook"),
}

SAFE_MESSAGES: dict[str, str] = {
    "policy_violation": "The requested action is not permitted by policy.",
    "unauthorized_actor": "This actor may not perform that transition.",
    "illegal_transition": "The case is not in a state that allows this action.",
    "invariant_violation": "A safety invariant was violated. The request was refused.",
    "invalid_amount": "The supplied amount is invalid.",
    "malformed_webhook": "The webhook request is missing required provider metadata.",
    "internal_error": "An unexpected error occurred.",
}


def classify(exc: Exception) -> tuple[int, str]:
    for exc_type, (status, code) in STATUS_MAP.items():
        if isinstance(exc, exc_type):
            return status, code
    if isinstance(exc, DomainError):
        return 400, "domain_error"
    return 500, "internal_error"


def error_body(code: str, request_id: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": SAFE_MESSAGES.get(code, SAFE_MESSAGES["internal_error"]),
            "request_id": request_id,
        }
    }
