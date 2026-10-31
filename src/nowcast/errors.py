"""Project exception types."""

from __future__ import annotations


class NowcastError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(NowcastError):
    """Raised when configuration or a required environment variable is invalid."""


class DataError(NowcastError):
    """Raised when an input file or dataset is missing or malformed."""


class RateLimited(NowcastError):
    """A provider asked us to wait; carries how long it asked for, in seconds."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        """Store the message and the provider's requested delay."""
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class BudgetExceeded(NowcastError):
    """Raised when the spend ledger reaches the configured budget cap."""
