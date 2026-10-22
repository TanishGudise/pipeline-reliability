"""Send model requests in order while keeping total token count under a per-minute budget (a sliding window).

The requests sent during the last minute (a send exactly one minute ago no longer counts)
may cost at most `tokens_per_minute` in total. Each request counts with its full token count from the moment it is sent.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, List, Tuple

from .window import SendWindow

log = logging.getLogger("tessera.pacing")


@dataclass
class PaceReport:
    sent: List[Tuple[str, float]] = field(default_factory=list)  # (request_id, clock time it was sent)
    failed: List[str] = field(default_factory=list)


class RequestPacer:
    def __init__(
        self,
        tokens_per_minute: float,
        send: Callable[[str], Awaitable[None]],
        cost: Callable[[str], float],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if tokens_per_minute <= 0:
            raise ValueError("tokens_per_minute must be positive")
        self._window = SendWindow(tokens_per_minute, 60.0, clock)
        self._send = send
        self._cost_of = cost
        self._clock = clock
        self._sleep = sleep

    async def run(self, items: Iterable[str]) -> PaceReport:
        """Send each request id in order, charging `cost(request_id)`. Each send finishes before the next budget check."""
        result = PaceReport()
        for item_id in items:
            cost = self._cost_of(item_id)
            if cost < 0:
                raise ValueError(f"negative token count for {item_id}")
            need = min(cost, self._window.budget)
            while True:
                wait = self._window.seconds_until_room(need)
                if wait <= 0:
                    break
                await self._sleep(wait)
            self._window.record(cost)
            result.sent.append((item_id, self._clock()))
            await self._send_one(item_id, result)
        return result

    async def _send_one(self, item_id: str, result: PaceReport) -> None:
        try:
            await self._send(item_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One failed send must not stop the others.
            log.exception("sending %s failed", item_id)
            result.failed.append(item_id)
