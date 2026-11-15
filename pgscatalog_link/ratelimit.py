"""Process-wide politeness limiter for the PGS Catalog REST API.

The PGS Catalog publishes no hard request limit; it is a shared EMBL-EBI service. The
default here is one request per 0.6 s (~100/min) plus a 20,000/UTC-day cap (both
env-configurable via ``PGSCATALOG_LINK_PGS__MIN_INTERVAL_S`` / ``__DAILY_CAP``). Every upstream request reserves the next slot; a call whose slot is
further away than ``max_wait_s``, or that would exceed the daily cap, is refused with a
typed ``rate_limited`` error carrying ``retry_after_s`` instead of queueing silently.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pgscatalog_link.exceptions import RateLimitedError


class RateLimiter:
    """Slot-reserving spacer (min interval between requests) with a UTC-day hit cap."""

    def __init__(
        self,
        *,
        min_interval_s: float,
        daily_cap: int,
        max_wait_s: float,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Configure spacing, the daily cap and the longest acceptable queue wait."""
        self.min_interval_s = min_interval_s
        self.daily_cap = daily_cap
        self.max_wait_s = max_wait_s
        self._monotonic = monotonic
        self._wall = wall
        self._sleep = sleep
        self._next_slot = 0.0
        self._day = ""
        self._count = 0
        self._refused = 0
        self._lock = asyncio.Lock()

    def _utc_now(self) -> datetime:
        return datetime.fromtimestamp(self._wall(), tz=UTC)

    async def acquire(self) -> None:
        """Wait for this request's slot, or raise ``RateLimitedError`` (retryable)."""
        async with self._lock:
            now_utc = self._utc_now()
            day = now_utc.date().isoformat()
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self.daily_cap:
                self._refused += 1
                midnight = datetime.combine(
                    now_utc.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
                )
                raise RateLimitedError(
                    f"Daily PGS Catalog request budget ({self.daily_cap}/UTC day) is exhausted. "
                    "Retry after the UTC day rolls over.",
                    retryable=True,
                    retry_after_s=round((midnight - now_utc).total_seconds(), 1),
                )
            now = self._monotonic()
            slot = max(now, self._next_slot)
            wait = slot - now
            if wait > self.max_wait_s:
                self._refused += 1
                raise RateLimitedError(
                    "The shared PGS Catalog request queue is full. "
                    "Retry after retry_after_s seconds.",
                    retryable=True,
                    retry_after_s=round(wait, 1),
                )
            self._next_slot = slot + self.min_interval_s
            self._count += 1
        if wait > 0:
            await self._sleep(wait)

    def stats(self) -> dict[str, Any]:
        """Configuration plus today's usage, for diagnostics."""
        return {
            "min_interval_s": self.min_interval_s,
            "daily_cap": self.daily_cap,
            "max_wait_s": self.max_wait_s,
            "requests_today": self._count,
            "refused_since_start": self._refused,
            "utc_day": self._day or None,
        }
