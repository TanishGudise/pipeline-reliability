"""Build a CSV table from a JSONL journal of results, and reuse the table on later calls."""

import csv
import json
import logging
import os
from typing import Callable, Dict, Iterator, List, Optional, Sequence

log = logging.getLogger("tablecache")

# Rows are flushed every FLUSH_EVERY rows so very large tables don't sit in memory.
FLUSH_EVERY = 64

Formatter = Callable[[dict], Optional[Dict[str, object]]]


class JournalError(ValueError):
    """A journal line could not be read."""


def read_journal(path: str) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise JournalError(f"{path}:{lineno}: unreadable journal entry") from e


def build_table(journal_path: str, table_path: str, formatter: Formatter, columns: Sequence[str]) -> int:
    """Write one CSV row per journal entry (the formatter may return None to skip an entry).

    Returns the number of rows written.
    """
    count = 0
    with open(table_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="raise")
        writer.writeheader()
        for entry in read_journal(journal_path):
            row = formatter(entry)
            if row is None:
                continue
            writer.writerow(row)
            count += 1
            if count % FLUSH_EVERY == 0:
                f.flush()
    log.info("wrote %d rows to %s", count, table_path)
    return count


def load_table(table_path: str) -> List[Dict[str, str]]:
    with open(table_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_or_build(journal_path: str, table_path: str, formatter: Formatter, columns: Sequence[str]) -> List[Dict[str, str]]:
    """Return the table at table_path, building it from the journal first if it doesn't exist.

    Building can be slow and the formatter can be expensive, so a table that exists is reused as is.
    Delete the table file to force a rebuild.
    """
    if os.path.exists(table_path):
        log.info("reusing %s", table_path)
        return load_table(table_path)
    build_table(journal_path, table_path, formatter, columns)
    return load_table(table_path)
