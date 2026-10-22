"""Start model server processes and wait until they are ready to serve."""

import asyncio
import logging
from typing import Awaitable, Callable, List, Sequence

log = logging.getLogger("tessera.serving")


class StartupError(RuntimeError):
    """The model server did not come up."""


class ServerExited(StartupError):
    """The model server process exited before it was ready."""

    def __init__(self, returncode: int, replica: int = 0):
        super().__init__(f"model server {replica} exited during startup with code {returncode}")
        self.returncode = returncode
        self.replica = replica


class StartupTimeout(StartupError):
    """The model server was not ready in time."""


class Server:
    """A running model server process."""

    def __init__(self, process):
        self.process = process

    async def stop(self, grace: float = 5.0) -> int:
        """Ask the process to exit, and kill it if it is still running `grace` seconds later."""
        if self.process.returncode is not None:
            return self.process.returncode
        self.process.terminate()
        try:
            return await asyncio.wait_for(self.process.wait(), grace)
        except asyncio.TimeoutError:
            log.warning("the model server did not exit within %.1fs; killing it", grace)
            self.process.kill()
            return await self.process.wait()


async def _spawn(command: Sequence[str]):
    return await asyncio.create_subprocess_exec(*command)


async def _is_ready(probe, *args) -> bool:
    """Whether the probe reports ready."""
    try:
        return bool(await probe(*args))
    except OSError:  # nothing is listening yet
        return False


async def start_servers(
    command: Sequence[str],
    ready: Callable[[int], Awaitable[object]],
    count: int,
    *,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
    spawn=_spawn,
) -> List[Server]:
    """Start `count` copies of `command` and return once `ready(i)` reports each of them ready, polling every
    `poll_interval` seconds. `timeout` is how long to wait for that."""
    servers = [Server(await spawn(command)) for _ in range(count)]
    log.info("waiting up to %.0fs for the model servers to be ready", timeout)
    deadline = asyncio.get_running_loop().time() + timeout
    pending = set(range(count))
    while True:
        pending = {i for i in pending if not await _is_ready(ready, i)}
        if not pending:
            return servers
        for i, server in enumerate(servers):
            code = server.process.returncode
            if code is not None:
                for other in servers:
                    await other.stop()
                raise ServerExited(code, replica=i)
        if asyncio.get_running_loop().time() >= deadline:
            for server in servers:
                await server.stop()
            raise StartupTimeout(f"the model servers were not ready after {timeout:g}s")
        await asyncio.sleep(poll_interval)
