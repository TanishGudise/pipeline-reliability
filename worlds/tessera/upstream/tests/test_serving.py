import asyncio

from tessera.serving import start_servers


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def is_running(self):
        return self.returncode is None

    @property
    def exit_code(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    async def wait(self, timeout=None):
        return self.returncode


def test_returns_once_ready_and_stops_cleanly():
    procs = []

    async def spawn(command):
        procs.append(FakeProcess())
        return procs[-1]

    async def probe(*args):
        return True

    async def main():
        started = await start_servers(["serve"], probe, 2, spawn=spawn)
        for s in started:
            await s.stop()
        return started

    asyncio.run(main())
    assert len(procs) == 2
    assert all(p.terminated for p in procs)
