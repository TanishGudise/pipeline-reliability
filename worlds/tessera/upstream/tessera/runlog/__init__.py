"""tessera.runlog: an append-only event log that survives crashes in the middle of a write."""

from .log import EventLog

__all__ = ["EventLog"]
