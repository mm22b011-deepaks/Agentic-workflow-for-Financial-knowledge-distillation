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


class AuthError(NowcastError):
    """The provider rejected the credential (401) or refused the request (403).

    Retrying cannot fix a wrong key, and doing so spends the retry budget and hides the
    real cause behind N identical failures, so the caller raises this instead.
    """


class ModelNotFound(NowcastError):
    """The model does not exist, or the provider rejected a parameter it does not support."""


class EmptyCompletion(NowcastError):
    """The model returned no content at all.

    Not a parse failure — there is nothing to parse — so it must not be fed to a repair
    loop, which would spend `1 + max_repairs` calls learning nothing.
    """

    def __init__(
        self, message: str, max_tokens: int, finish_reason: str = '', completion_tokens: int = 0
    ) -> None:
        """Store the message, the budget in force, the finish reason and tokens spent."""
        super().__init__(message)
        self.max_tokens = max_tokens
        self.finish_reason = finish_reason
        self.completion_tokens = completion_tokens


class TruncatedCompletion(EmptyCompletion):
    """An empty reply whose `finish_reason` says the token budget ran out.

    A reasoning model that spends the whole budget thinking returns `content: ''` with
    `finish_reason: 'length'`, which a larger budget can fix.
    """
