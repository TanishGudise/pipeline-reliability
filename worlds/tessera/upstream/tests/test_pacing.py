import asyncio

from tessera.pacing import RequestPacer


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)


async def noop(item_id):
    return None


COSTS = {"a": 30, "b": 30, "c": 40}


def test_items_within_budget_are_sent_immediately():
    clock = FakeClock()
    d = RequestPacer(100, noop, COSTS.__getitem__, clock=clock, sleep=clock.sleep)
    result = asyncio.run(d.run(["a", "b", "c"]))
    assert [item for item, _ in result.sent] == ["a", "b", "c"]
    assert all(t == 0.0 for _, t in result.sent)
