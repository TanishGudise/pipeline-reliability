"""meter: send work items in order under a per-minute cost budget."""

from .dispatcher import Dispatcher, DispatchResult

__all__ = ["DispatchResult", "Dispatcher"]
