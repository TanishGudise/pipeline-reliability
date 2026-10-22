import asyncio

from tessera.client import ModelClient, TransientError


def test_transient_errors_are_retried():
    attempts = []

    async def send(request):
        attempts.append(request)
        if attempts.count(request) == 1:
            raise TransientError("busy")
        return f"reply:{request}"

    async def main():
        client = ModelClient(send, max_in_flight=2, backoff=0.01)
        return await asyncio.gather(client.call("a"), client.call("b"))

    assert asyncio.run(main()) == ["reply:a", "reply:b"]
    assert sorted(attempts) == ["a", "a", "b", "b"]
