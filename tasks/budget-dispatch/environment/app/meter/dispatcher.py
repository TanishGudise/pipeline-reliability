"""Send items in order while keeping total cost under a per-minute budget (a token bucket).

The budget refills continuously at `budget_per_minute / 60` per second and never holds more
than `budget_per_minute`. Each item is charged its full cost when it is sent.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, List, Tuple

log = logging.getLogger("meter")


@dataclass
class DispatchResult:
    sent: List[Tuple[str, float]] = field(default_factory=list)  # (item_id, clock time it was sent)
    failed: List[str] = field(default_factory=list)


class Dispatcher:
    def __init__(
        self,
        budget_per_minute: float,
        send: Callable[[str], Awaitable[None]],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_interval: float = 0.1,
    ):
        if budget_per_minute <= 0:
            raise ValueError("budget_per_minute must be positive")
        self._budget = float(budget_per_minute)
        self._rate = self._budget / 60.0
        self._available = self._budget  # start with a full budget
        self._last_refill = None
        self._send = send
        self._clock = clock
        self._sleep = sleep
        self._poll_interval = poll_interval

    def _refill(self) -> None:
        now = self._clock()
        if self._last_refill is not None:
            # Cap at the budget so an idle period can't be saved up for a burst.
            self._available = min(self._available + (now - self._last_refill) * self._rate, self._budget)
        self._last_refill = now

    def _has_capacity(self, cost: float) -> bool:
        self._refill()
        return self._available >= cost

    async def run(self, items: Iterable[Tuple[str, float]]) -> DispatchResult:
        """Send each (item_id, cost) in order. Sends run concurrently; budget checks are in order."""
        result = DispatchResult()
        tasks = []
        for item_id, cost in items:
            if cost < 0:
                raise ValueError(f"negative cost for {item_id}")
            while not self._has_capacity(cost):
                await self._sleep(self._poll_interval)
            self._available -= cost
            result.sent.append((item_id, self._clock()))
            tasks.append(asyncio.create_task(self._send_one(item_id, result)))
        await asyncio.gather(*tasks)
        return result

    async def _send_one(self, item_id: str, result: DispatchResult) -> None:
        try:
            await self._send(item_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One failed send must not stop the others.
            log.exception("sending %s failed", item_id)
            result.failed.append(item_id)
