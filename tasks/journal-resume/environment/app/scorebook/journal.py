"""Append-only JSONL journal of model replies, used to resume interrupted runs."""

import json
import os
from typing import Dict


class Journal:
    """Stores one entry per record: the record id and the raw model reply."""

    def __init__(self, path: str):
        self.path = path

    def append(self, record_id: str, reply: str) -> None:
        line = json.dumps({"id": record_id, "reply": reply}) + "\n"
        # One write per entry. A crash mid-write leaves at most one torn last line,
        # which load() skips, so that record is simply scored again on the next run.
        with open(self.path, "a+b") as f:
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    f.write(b"\n")  # start after a torn line, never inside it
            f.write(line.encode("utf-8"))

    def load(self) -> Dict[str, str]:
        """Return {record_id: reply} for every complete entry in the journal."""
        replies: Dict[str, str] = {}
        if not os.path.exists(self.path):
            return replies
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                replies[entry["id"]] = entry["reply"]
        return replies

    def __len__(self) -> int:
        return len(self.load())
