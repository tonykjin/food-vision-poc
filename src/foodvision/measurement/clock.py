"""Clocks: monotonic nanoseconds for durations, timezone-aware UTC for event timestamps.

Never subtract wall-clock timestamps to get a duration, and never compare monotonic
readings across processes or machines (plan §10).
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def monotonic_ns(self) -> int: ...
    def utc_now(self) -> datetime: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic_ns(self) -> int:
        return time.perf_counter_ns()

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class ManualClock:
    """Deterministic clock for tests. `sleep` and `advance` move both readings together."""

    def __init__(self, start_utc: datetime | None = None) -> None:
        self._ns = 0
        self._utc = start_utc or datetime(2026, 1, 1, tzinfo=UTC)
        self.sleeps: list[float] = []

    def monotonic_ns(self) -> int:
        return self._ns

    def utc_now(self) -> datetime:
        return self._utc

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a monotonic clock cannot go backwards")
        self._ns += round(seconds * 1e9)
        self._utc += timedelta(seconds=seconds)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)
