import asyncio
from collections import Counter

from scorebook import Runner


class FakeModel:
    def __init__(self):
        self.calls = Counter()

    async def score(self, text):
        self.calls[text] += 1
        return f"label for {text}"


def postprocess(record, reply):
    return {"id": record["id"], "label": reply}


RECORDS = [{"id": f"r{i}", "text": f"text {i}"} for i in range(5)]


def test_run_scores_every_record(tmp_path):
    model = FakeModel()
    rows = asyncio.run(Runner(model, postprocess, str(tmp_path / "journal.jsonl")).run(RECORDS))
    assert [row["id"] for row in rows] == [record["id"] for record in RECORDS]
    assert sum(model.calls.values()) == len(RECORDS)


def test_second_run_reuses_the_journal(tmp_path):
    model = FakeModel()
    journal = str(tmp_path / "journal.jsonl")
    asyncio.run(Runner(model, postprocess, journal).run(RECORDS))
    rows = asyncio.run(Runner(model, postprocess, journal).run(RECORDS))
    assert len(rows) == len(RECORDS)
    assert sum(model.calls.values()) == len(RECORDS)
