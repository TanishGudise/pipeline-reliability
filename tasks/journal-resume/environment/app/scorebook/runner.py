"""Score records with a model, turn each reply into rows with a user hook, and resume from a journal."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

from .journal import Journal

log = logging.getLogger("scorebook")

Row = dict


class TransientModelError(Exception):
    """Raised by a model client for errors worth retrying (timeouts, overload)."""


class IncompleteRunError(Exception):
    """Raised at the end of a run when require_all=True and some records have no rows."""

    def __init__(self, missing: Iterable[str], failed: Iterable[str]):
        self.missing = sorted(missing)
        self.failed = sorted(failed)
        super().__init__(
            f"run incomplete: {len(self.missing)} record(s) without a model reply {self.missing}, "
            f"{len(self.failed)} record(s) failed post-processing {self.failed}"
        )


@dataclass
class RunStats:
    model_calls: int = 0
    rows: int = 0
    dropped: List[str] = field(default_factory=list)


class Runner:
    """Runs `model.score(text)` once per record and keeps the replies in a journal.

    `postprocess(record, reply)` turns a reply into a row (dict), a list of rows, or [] to drop
    the record on purpose. Rows are always rebuilt from the journal at the end of a run, so a
    changed `postprocess` applies to replies that were already paid for.
    """

    def __init__(
        self,
        model,
        postprocess: Callable[[dict, str], object],
        journal_path: str,
        *,
        concurrency: int = 4,
        max_attempts: int = 3,
        require_all: bool = True,
        on_rows: Optional[Callable[[str, List[Row]], None]] = None,
    ):
        self._model = model
        self._postprocess = postprocess
        self._journal = Journal(journal_path)
        self._concurrency = concurrency
        self._max_attempts = max_attempts
        self._require_all = require_all
        self._on_rows = on_rows
        self.stats = RunStats()

    async def run(self, records: List[dict]) -> List[Row]:
        done = self._journal.load()
        todo = [record for record in records if record["id"] not in done]
        log.info("%d of %d records already have a reply", len(records) - len(todo), len(records))

        semaphore = asyncio.Semaphore(self._concurrency)

        async def worker(record):
            async with semaphore:
                await self._score(record)

        await asyncio.gather(*(worker(record) for record in todo))
        return self._collect(records)

    async def _call_model(self, record: dict) -> Optional[str]:
        for attempt in range(1, self._max_attempts + 1):
            self.stats.model_calls += 1
            try:
                return await self._model.score(record["text"])
            except TransientModelError as e:
                log.warning("attempt %d/%d for %s failed: %s", attempt, self._max_attempts, record["id"], e)
        return None

    async def _score(self, record: dict) -> None:
        reply = await self._call_model(record)
        if reply is None:
            return
        try:
            rows = _as_rows(self._postprocess(record, reply))
        except Exception as e:
            log.warning("postprocess failed for %s: %s", record["id"], e)
            return
        if not rows:
            return
        self._journal.append(record["id"], reply)
        self._notify(record["id"], rows)

    def _notify(self, record_id: str, rows: List[Row]) -> None:
        if self._on_rows is None:
            return
        try:
            self._on_rows(record_id, rows)
        except Exception:
            # A progress callback must never break a run.
            log.exception("on_rows callback failed for %s", record_id)

    def _collect(self, records: List[dict]) -> List[Row]:
        replies = self._journal.load()
        rows: List[Row] = []
        missing, failed = [], []
        for record in records:
            record_id = record["id"]
            if record_id not in replies:
                missing.append(record_id)
                continue
            try:
                produced = _as_rows(self._postprocess(record, replies[record_id]))
            except Exception as e:
                log.warning("postprocess failed for %s: %s", record_id, e)
                failed.append(record_id)
                continue
            if not produced:
                self.stats.dropped.append(record_id)
            rows.extend(produced)
        self.stats.rows = len(rows)
        if self._require_all and (missing or failed):
            raise IncompleteRunError(missing, failed)
        return rows


def _as_rows(value) -> List[Row]:
    if value is None:
        raise TypeError("postprocess returned None; return a row, a list of rows, or [] to drop the record")
    rows = value if isinstance(value, list) else [value]
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError(f"postprocess must return dict rows, got {type(row).__name__}")
    return rows
