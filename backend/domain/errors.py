"""Domain and application errors; interfaces translate them into HTTP codes or CLI messages."""

from __future__ import annotations


class ColdKeeperError(Exception):
    """Base class: the message is safe to show to the user (Russian)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationFailedError(ColdKeeperError):
    """Input breaks a business rule."""


class NotFoundError(ColdKeeperError):
    """The object does not exist or belongs to another organization (indistinguishable on purpose)."""


class PermissionDeniedError(ColdKeeperError):
    """The actor's role does not allow the action."""


class ConflictError(ColdKeeperError):
    """The action conflicts with stored state (duplicates, overlapping periods, dependent data)."""


class AuthenticationError(ColdKeeperError):
    """Wrong credentials, expired session or revoked device token."""


class RateLimitedError(ColdKeeperError):
    """Too many failed attempts; retry later."""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
