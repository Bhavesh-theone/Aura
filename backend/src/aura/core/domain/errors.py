class DomainError(Exception):
    """Base for rule violations the API maps to HTTP errors."""


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass


class RuleViolation(DomainError):
    """Input breaks a domain rule (maps to 422)."""


class Forbidden(DomainError):
    """The actor's role does not allow this action (maps to 403)."""


class HandoffRejected(RuleViolation):
    """A malformed handoff or directive. Its audit row is the point, so it is kept."""
    persist_writes = True


class InvalidTransition(DomainError):
    """Stage move not permitted by the stage machine (maps to 409)."""


class GuardBlocked(DomainError):
    # The blocked attempt's evaluation rows and audit entry are the point: the unit of
    # work commits them even though the request fails.
    persist_writes = True

    def __init__(self, message: str, evaluations: list):
        super().__init__(message)
        self.evaluations = evaluations


class RateLimited(DomainError):
    """Too many requests (maps to 429 with Retry-After)."""

    def __init__(self, message: str, retry_after_seconds: float):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class CapabilityDisabled(Conflict):
    """The capability's autonomy level is 0 (maps to 409). Permanent for a segment."""
