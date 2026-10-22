"""The job runner: pace the prompts within the token budget, send them with retries, log every event."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
import time
import urllib.error
import urllib.request
from typing import Awaitable, Callable, Dict, List, Optional

from .client import ModelClient
from .config import JobConfig
from .pacing import RequestPacer
from .prompts import Prompt, load_prompts
from .results import write_results
from .runlog import EventLog
from .serving import start_servers
from .transport import HttpTransport

Transport = Callable[[Prompt], Awaitable[str]]


@dataclasses.dataclass
class JobSummary:
    name: str
    ok: int = 0
    failed: int = 0
    log_path: Optional[pathlib.Path] = None
    output: Optional[pathlib.Path] = None


def _health_url(config: JobConfig, replica: int) -> str:
    return f"http://{config.server.host}:{config.server.port(replica)}/health"


async def http_ready(config: JobConfig, replica: int) -> bool:
    """Whether the replica's /health answers 200. Raises OSError while nothing listens on the port."""

    def probe() -> bool:
        try:
            with urllib.request.urlopen(_health_url(config, replica), timeout=2) as response:
                return response.status == 200
        except urllib.error.HTTPError:
            return False

    return await asyncio.to_thread(probe)


class JobRunner:
    """Runs one job. Tests pass their own transport, clock and sleep, and stand-ins for the servers."""

    def __init__(self, config: JobConfig, transport: Optional[Transport] = None, *, clock=time.monotonic,
                 sleep=asyncio.sleep, spawn=None, ready=None):
        self.config = config
        self.transport = transport or HttpTransport(config.client.endpoint, config.model, config.client.timeout)
        self.clock = clock
        self.sleep = sleep
        self.spawn = spawn
        self.ready = ready or (lambda replica: http_ready(config, replica))

    def log_path(self) -> pathlib.Path:
        return self.config.log_dir / f"{self.config.name}.jsonl"

    async def start_servers(self):
        """Start the job's model servers, replacing "{port}" in each replica's command with its port."""
        server = self.config.server
        ports = iter(range(server.base_port, server.base_port + server.replicas))

        async def spawn(command):
            # start_servers starts the replicas in order, so the next port is this replica's.
            port = str(next(ports))
            command = [arg.replace("{port}", port) for arg in command]
            if self.spawn is not None:
                return await self.spawn(command)
            return await asyncio.create_subprocess_exec(*command)

        return await start_servers(server.command, self.ready, server.replicas, timeout=server.startup_timeout,
                                   poll_interval=server.poll_interval, spawn=spawn)

    async def run(self) -> JobSummary:
        prompts = load_prompts(self.config.prompts)
        by_id: Dict[str, Prompt] = {p.id: p for p in prompts}
        attempts: Dict[str, int] = {}
        results: Dict[str, dict] = {}
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        log = EventLog(str(self.log_path()))
        log.append({"event": "start", "job": self.config.name, "prompts": len(prompts)})
        servers: List = []
        try:
            if self.config.server.command:
                servers = await self.start_servers()
                log.append({"event": "servers", "replicas": len(servers)})

            async def attempt(prompt: Prompt) -> str:
                attempts[prompt.id] = attempts.get(prompt.id, 0) + 1
                return await self.transport(prompt)

            client = ModelClient(attempt, max_in_flight=self.config.client.max_in_flight,
                                 max_attempts=self.config.client.max_attempts, backoff=self.config.client.backoff)

            async def send(prompt_id: str) -> None:
                prompt = by_id[prompt_id]
                log.append({"event": "send", "id": prompt_id, "tokens": prompt.estimated_tokens()})
                try:
                    text = await client.call(prompt)
                except Exception as e:  # recorded as a failed prompt; the job goes on
                    results[prompt_id] = {"id": prompt_id, "status": "failed", "error": f"{type(e).__name__}: {e}"}
                    log.append({"event": "failed", "id": prompt_id, "error": results[prompt_id]["error"]})
                else:
                    results[prompt_id] = {"id": prompt_id, "status": "ok", "text": text}
                    log.append({"event": "done", "id": prompt_id})

            pacer = RequestPacer(self.config.budget.tokens_per_minute, send, lambda pid: by_id[pid].estimated_tokens(),
                                 clock=self.clock, sleep=self.sleep)
            await pacer.run([p.id for p in prompts])
        finally:
            for server in servers:
                await server.stop()
            log.append({"event": "end", "job": self.config.name})
            close = getattr(log, "close", None)  # run logs before 0.4.2 had no close()
            if close is not None:
                close()
        rows = [dict(results[p.id], attempts=attempts.get(p.id, 0)) for p in prompts if p.id in results]
        write_results(self.config.output, rows)
        return JobSummary(self.config.name, ok=sum(r["status"] == "ok" for r in rows),
                          failed=sum(r["status"] == "failed" for r in rows), log_path=self.log_path(),
                          output=self.config.output)


def summarize_log(path) -> dict:
    """Event counts in a run log, and the prompts that failed."""
    counts: Dict[str, int] = {}
    failed: List[str] = []
    for event in EventLog(str(path)).read():
        counts[event.get("event", "?")] = counts.get(event.get("event", "?"), 0) + 1
        if event.get("event") == "failed":
            failed.append(event.get("id"))
    return {"events": counts, "failed": failed}


def dumps_summary(summary: dict) -> str:
    return json.dumps(summary, indent=2, sort_keys=True)
