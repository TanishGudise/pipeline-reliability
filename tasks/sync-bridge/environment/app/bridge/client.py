"""A small async lookup client and its synchronous wrapper."""

import asyncio
from typing import Awaitable, Callable, Dict, Iterable

from .runner import run_sync


class LookupError_(Exception):
    """A key could not be looked up."""


class AsyncLookupClient:
    """Looks keys up through `fetch(key)` with a per-request timeout and limited concurrency."""

    def __init__(self, fetch: Callable[[str], Awaitable[str]], *, timeout: float = 30.0, concurrency: int = 8):
        self._fetch = fetch
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(concurrency)

    async def get(self, key: str) -> str:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(self._fetch(key), self._timeout)
            except asyncio.TimeoutError as e:
                raise LookupError_(f"timed out looking up {key!r}") from e

    async def get_many(self, keys: Iterable[str]) -> Dict[str, str]:
        keys = list(keys)
        values = await asyncio.gather(*(self.get(key) for key in keys))
        return dict(zip(keys, values))


class LookupClient:
    """Synchronous facade: each call runs the async client to completion."""

    def __init__(self, fetch: Callable[[str], Awaitable[str]], **kwargs):
        self._fetch = fetch
        self._kwargs = kwargs

    def get(self, key: str) -> str:
        return run_sync(self._client().get(key))

    def get_many(self, keys: Iterable[str]) -> Dict[str, str]:
        return run_sync(self._client().get_many(keys))

    def _client(self) -> AsyncLookupClient:
        # A fresh async client per call: its semaphore belongs to the loop that runs the call.
        return AsyncLookupClient(self._fetch, **self._kwargs)
