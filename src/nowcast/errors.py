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


class TruncatedCompletion(NowcastError):
    """The model returned no content because its token budget ran out.

    A reasoning model that spends the whole budget thinking returns `content: ''` with
    `finish_reason: 'length'`. That is not a parse failure — there is nothing to parse —
    so it must be retried with a larger budget rather than fed to a repair loop.
    """

    def __init__(self, message: str, max_tokens: int, completion_tokens: int = 0) -> None:
        """Store the message and the budget that was exhausted."""
        super().__init__(message)
        self.max_tokens = max_tokens
        self.completion_tokens = completion_tokens
