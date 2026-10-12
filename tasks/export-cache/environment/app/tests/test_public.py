import json

from tablecache import load_or_build


def write_journal(path, n):
    with open(path, "w") as f:
        for i in range(n):
            f.write(json.dumps({"id": i, "score": i * 2}) + "\n")


def fmt(entry):
    return {"id": entry["id"], "score": entry["score"]}


def test_builds_then_reuses(tmp_path):
    journal, table = tmp_path / "j.jsonl", tmp_path / "out" / "table.csv"
    table.parent.mkdir()
    write_journal(journal, 10)
    rows = load_or_build(str(journal), str(table), fmt, ["id", "score"])
    assert [row["id"] for row in rows] == [str(i) for i in range(10)]
    calls = []
    rows = load_or_build(str(journal), str(table), lambda e: calls.append(e) or fmt(e), ["id", "score"])
    assert len(rows) == 10 and calls == []
