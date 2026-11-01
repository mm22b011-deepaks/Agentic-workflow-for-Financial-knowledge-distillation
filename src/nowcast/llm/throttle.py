"""Request pacing for free models: a shared rate limit, a request budget and a cooldown.

Free tiers are limited by requests, not by dollars, so a spend cap is not a budget at
all. One limiter is shared by every caller and every thread in a run: per-thread pacing
would multiply the limit by the worker count, which is exactly how a free tier gets a
run blocked. A provider's "retry after" pauses the whole limiter, because the next call
would be refused for the same reason.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RequestLimiter:
    """Cap requests per minute and per day, with a shared cooldown."""

    def __init__(
        self,
        per_minute: int,
        per_day: int,
        cooldown_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Store the limits; `clock` and `sleep` exist so tests do not wait."""
        self._per_minute = max(1, int(per_minute))
        self._per_day = max(1, int(per_day))
        self._cooldown = float(cooldown_seconds)
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._day_start = self._clock()
        self._day_count = 0
        self._resume_at = 0.0
        self._lock = threading.Lock()

    @property
    def requests_today(self) -> int:
        """Return how many requests were sent since the current day started."""
        with self._lock:
            return self._day_count

    def cooldown(self, seconds: float) -> None:
        """Pause every caller until `seconds` from now; never shortens an active pause."""
        until = self._clock() + max(0.0, float(seconds))
        with self._lock:
            self._resume_at = max(self._resume_at, until)

    def acquire(self) -> None:
        """Wait until one more request may be sent, then count it.

        A request that would exceed the daily budget raises `BudgetExceeded` rather than
        sleeping until midnight.
        """
        from nowcast.errors import BudgetExceeded

        while True:
            with self._lock:
                now = self._clock()
                if now - self._day_start >= 86400:
                    self._day_start = now
                    self._day_count = 0
                if self._day_count >= self._per_day:
                    raise BudgetExceeded(
                        f'request budget exhausted: {self._day_count} of {self._per_day} today'
                    )
                while self._sent and now - self._sent[0] >= 60.0:
                    self._sent.popleft()
                wait_cooldown = self._resume_at - now
                wait_rate = (
                    60.0 - (now - self._sent[0]) if len(self._sent) >= self._per_minute else 0.0
                )
                wait = max(wait_cooldown, wait_rate, 0.0)
                if wait <= 0:
                    self._sent.append(now)
                    self._day_count += 1
                    return
            self._sleep(wait)
