"""Domain errors. Loud failure is a feature, not a bug."""


class DomainError(Exception):
    """Base class for all domain rule violations."""


class InvariantViolation(DomainError):
    """A system invariant was broken. This must never be swallowed."""


class IllegalTransition(DomainError):
    """An attempt was made to move a case along a path that does not exist."""


class UnauthorizedActor(InvariantViolation):
    """An actor attempted a transition it is not permitted to make."""


class PolicyViolation(DomainError):
    """An action was attempted without policy authorization."""


class MoneyError(DomainError):
    """An invalid monetary value or operation."""


class MissingProviderEventId(DomainError):
    """A provider event arrived with no event id.

    Treated as malformed rather than recoverable: without a stable identifier
    supplied by the provider, exactly-once processing of a payment event cannot
    be guaranteed. See docs/IMPLEMENTATION_DECISIONS.md, D11.
    """
