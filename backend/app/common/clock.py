"""Authoritative time source. All canonical timestamps are integer UTC milliseconds."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...


class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


class FakeClock:
    """Deterministic clock for tests."""

    def __init__(self, start_ms: int = 1_790_000_000_000) -> None:
        self._now = start_ms
        self._lock = threading.Lock()

    def now_ms(self) -> int:
        with self._lock:
            return self._now

    def advance(self, ms: int) -> int:
        with self._lock:
            self._now += ms
            return self._now

    def set(self, ms: int) -> None:
        with self._lock:
            self._now = ms


def ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def utc_date_id(ms: int) -> str:
    """UTC calendar day, e.g. ``2026-09-27``."""
    return ms_to_datetime(ms).strftime("%Y-%m-%d")


def iso_week_id(ms: int) -> str:
    """UTC ISO week, e.g. ``2026-W39``."""
    year, week, _ = ms_to_datetime(ms).isocalendar()
    return f"{year}-W{week:02d}"


def next_utc_midnight_ms(ms: int) -> int:
    day = 86_400_000
    return (ms // day + 1) * day


def next_iso_week_start_ms(ms: int) -> int:
    dt = ms_to_datetime(ms)
    day = 86_400_000
    midnight = (ms // day) * day
    return midnight + (7 - dt.weekday()) * day
