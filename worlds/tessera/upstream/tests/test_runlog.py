from tessera.runlog import EventLog


def entry(i):
    return {"id": i, "kind": f"k{i}", "value": f"v{i}"}


def test_round_trip(tmp_path):
    path = str(tmp_path / "events.jsonl")
    log = EventLog(path)
    log.append(entry(0))
    assert list(log.read()) == [entry(i) for i in range(1)]


def test_incomplete_last_line_is_skipped(tmp_path):
    path = tmp_path / "events.jsonl"
    log = EventLog(str(path))
    log.append(entry(0))
    with open(path, "ab") as f:
        f.write(b'{"id": 9')
    assert list(EventLog(str(path)).read()) == [entry(0)]
