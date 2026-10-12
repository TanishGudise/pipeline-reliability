"""Run a coroutine to completion from synchronous code.

Works from plain scripts and from code that already runs inside an event loop (for example a
Jupyter notebook cell), where asyncio.run() refuses to start.
"""

import asyncio
import concurrent.futures

# asyncio.run() raises a RuntimeError containing this text when the calling thread already runs an
# event loop.
_NESTED_LOOP_HINT = "running event loop"


def run_sync(coro):
    """Run `coro` and return its result, or raise the exception it raised."""
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:
        if _NESTED_LOOP_HINT not in str(exc):
            raise
    # This thread already runs an event loop: give the coroutine a fresh loop on a worker thread.
    return _run_on_worker_thread(coro)


def _run_on_worker_thread(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="bridge") as pool:
        return pool.submit(asyncio.run, coro).result()
