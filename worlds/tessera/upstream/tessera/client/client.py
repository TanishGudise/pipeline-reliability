"""An async client for the model API: at most `max_in_flight` requests in flight, transient errors retried."""

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("tessera.client")


class TransientError(Exception):
    """A failure worth retrying: rate limited, overloaded or temporarily unavailable."""


class ModelClient:
    def __init__(
        self,
        send: Callable[[object], Awaitable[object]],
        *,
        max_in_flight: int = 8,
        max_attempts: int = 4,
        backoff: float = 0.5,
        max_backoff: float = 8.0,
    ):
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be at least 1")
        self._send = send
        self._max_in_flight = max_in_flight
        self._max_attempts = max_attempts
        self._backoff = backoff
        self._max_backoff = max_backoff
        self._slots = asyncio.Semaphore(max_in_flight)

    def _delay(self, attempt: int) -> float:
        """How long to wait before `attempt` (2 is the first retry)."""
        return min(self._backoff * 2 ** (attempt - 2), self._max_backoff)

    async def call(self, request: object) -> object:
        """Send one request, retrying `TransientError` with backoff.

        Raises the last error after `max_attempts` failed attempts.
        """
        async with self._slots:
            try:
                return await self._send(request)
            except TransientError as e:
                error = e
        for attempt in range(2, self._max_attempts + 1):
            delay = self._delay(attempt)
            log.info("%s failed (%s); attempt %d in %.1fs", request, error, attempt, delay)
            await asyncio.sleep(delay)
            async with self._slots:
                try:
                    return await self._send(request)
                except TransientError as e:
                    error = e
        raise error
