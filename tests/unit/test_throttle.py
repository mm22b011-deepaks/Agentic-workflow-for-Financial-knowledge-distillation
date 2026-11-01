"""H-a: one shared request limit, one shared cooldown."""

from __future__ import annotations

import threading

import pytest

from nowcast.errors import BudgetExceeded
from nowcast.llm.throttle import RequestLimiter


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        """Start at zero."""
        self.now = 0.0

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance time instead of waiting."""
        self.now += max(0.0, seconds)


def test_limiter_caps_rpm_across_threads() -> None:
    """Threads share one per-minute cap; they cannot multiply it by their count."""
    clock = FakeClock()
    limiter = RequestLimiter(per_minute=5, per_day=1000, clock=clock, sleep=clock.sleep)
    stamps: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(5):
            limiter.acquire()
            with lock:
                stamps.append(clock.now)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stamps.sort()
    assert len(stamps) == 20
    # Any 60-second window holds at most the configured five requests.
    for index in range(len(stamps) - 5):
        assert stamps[index + 5] - stamps[index] >= 60.0


def test_global_cooldown_on_retry_after() -> None:
    """A provider cooldown delays every caller, not only the one that was refused."""
    clock = FakeClock()
    limiter = RequestLimiter(per_minute=100, per_day=1000, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.cooldown(30.0)
    started = clock.now
    limiter.acquire()
    assert clock.now - started >= 30.0


def test_daily_budget_raises_instead_of_sleeping() -> None:
    """Exhausting the day's requests is a stop, not a wait until midnight."""
    clock = FakeClock()
    limiter = RequestLimiter(per_minute=100, per_day=2, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    with pytest.raises(BudgetExceeded, match='request budget'):
        limiter.acquire()
