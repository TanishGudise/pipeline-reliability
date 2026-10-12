import asyncio

from bridge import LookupClient


async def fetch(key):
    await asyncio.sleep(0)
    return key.upper()


def test_get_many_from_a_script():
    assert LookupClient(fetch).get_many(["a", "b"]) == {"a": "A", "b": "B"}


def test_get_from_inside_a_running_loop():
    async def notebook_cell():
        return LookupClient(fetch).get("x")

    assert asyncio.run(notebook_cell()) == "X"
