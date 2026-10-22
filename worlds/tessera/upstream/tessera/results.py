"""Writing results: JSON Lines, or CSV when the output file ends in .csv."""

from __future__ import annotations

import csv
import json
import pathlib
from typing import Iterable

FIELDS = ["id", "status", "attempts", "text", "error"]


def write_results(path, rows: Iterable[dict]) -> int:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    # TODO: write to a temporary file first; a crash here leaves a half-written results file.
    with open(path, "w", encoding="utf-8", newline="") as f:
        if path.suffix == ".csv":
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        else:
            for row in rows:
                f.write(json.dumps({k: row.get(k) for k in FIELDS}) + "\n")
    return len(rows)
