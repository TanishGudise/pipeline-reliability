"""An append-only event log, one event per line (JSON Lines).

A process that crashes in the middle of a write can leave an incomplete last line. Readers skip
lines they can't parse, so an incomplete event is simply not there.
"""

import json
import logging
import os
from typing import Iterator, List

log = logging.getLogger("tessera.runlog")


def _encode(event: dict) -> str:
    return json.dumps(event, sort_keys=True) + "\n"


def _decode(line: str):
    """The event on one line, or None if the line is incomplete."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _open_for_append(path: str):
    f = open(path, "a+b")
    if f.tell() > 0:
        f.seek(-1, os.SEEK_END)
        if f.read(1) != b"\n":
            f.write(b"\n")  # a crash left an incomplete last line: start on a new line
    return f


def _read_file(path: str) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            event = _decode(line)
            if event is None:
                log.warning("%s:%d: skipping an incomplete event", path, lineno)
                continue
            yield event


class EventLog:
    def __init__(self, path: str):
        self.path = path

    def append(self, event: dict) -> None:
        """Add one event at the end of the log."""
        with _open_for_append(self.path) as f:
            f.write(_encode(event).encode("utf-8"))

    def read(self) -> List[dict]:
        """Every complete event, oldest first."""
        if not os.path.exists(self.path):
            return []
        return list(_read_file(self.path))
