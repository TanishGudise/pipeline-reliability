"""bridge: a synchronous facade over an async lookup client."""

from .client import AsyncLookupClient, LookupClient, LookupError_
from .runner import run_sync

__all__ = ["AsyncLookupClient", "LookupClient", "LookupError_", "run_sync"]
