"""A sliding window over recent sends: at most `budget` in total during the last `period` seconds."""

import time
from collections import deque
from typing import Callable, Deque, Tuple

# Float rounding can leave a send a hair inside the window at the moment it should drop out.
EPSILON = 1e-9


class SendWindow:
    """Remembers the cost of every send during the last `period` seconds."""

    def __init__(self, budget: float, period: float, clock: Callable[[], float] = time.monotonic):
        self.budget = float(budget)
        self.period = float(period)
        self._clock = clock
        self._sends: Deque[Tuple[float, float]] = deque()  # (clock time, cost)

    def spent(self) -> float:
        """Total cost sent during the last period (a send exactly one period ago no longer counts)."""
        now = self._clock()
        while self._sends and self._sends[0][0] <= now - self.period + EPSILON:
            self._sends.popleft()
        return sum(cost for _, cost in self._sends)

    def seconds_until_room(self, amount: float) -> float:
        """How long until `amount` more fits in the window (0 if it fits now)."""
        if self.spent() + amount <= self.budget + EPSILON:
            return 0.0
        # The oldest send leaves the window first; check again then.
        oldest = self._sends[0][0] if self._sends else self._clock()
        return oldest + self.period - self._clock()

    def record(self, cost: float) -> None:
        self._sends.append((self._clock(), cost))
