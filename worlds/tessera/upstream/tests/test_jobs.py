import asyncio
import json

from click.testing import CliRunner

from tessera.cli import cli
from tessera.client import TransientError
from tessera.config import load_config
from tessera.jobs import JobRunner, summarize_log


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)


def test_job_runs_every_prompt_and_logs_it(job_dir):
    config = load_config(job_dir / "job.yaml")
    clock = FakeClock()
    calls = []

    async def transport(prompt):
        calls.append(prompt.id)
        if prompt.id == "p2" and calls.count("p2") == 1:
            raise TransientError("503")
        if prompt.id == "p4":
            raise ValueError("bad prompt")
        return f"summary of {prompt.id}"

    summary = asyncio.run(JobRunner(config, transport, clock=clock, sleep=clock.sleep).run())
    assert (summary.ok, summary.failed) == (5, 1)
    rows = [json.loads(line) for line in config.output.read_text().splitlines()]
    assert [r["id"] for r in rows] == [f"p{i}" for i in range(6)]
    assert rows[2]["attempts"] == 2 and rows[2]["status"] == "ok"
    assert rows[4]["status"] == "failed" and "bad prompt" in rows[4]["error"]
    log = summarize_log(summary.log_path)
    assert log["events"]["send"] == 6 and log["events"]["done"] == 5 and log["failed"] == ["p4"]
    assert log["events"]["start"] == log["events"]["end"] == 1


def test_job_stays_within_the_token_budget(job_dir):
    config = load_config(job_dir / "job.yaml")
    config.budget.tokens_per_minute = 150  # the prompts cost 50-77 tokens each: they can't all go in one minute
    clock = FakeClock()
    sent = []

    async def transport(prompt):
        sent.append((clock(), prompt.estimated_tokens()))
        return "ok"

    summary = asyncio.run(JobRunner(config, transport, clock=clock, sleep=clock.sleep).run())
    # How the window is counted is tests/test_pacing.py's business; here: everything went out, and pacing
    # made the job wait.
    assert summary.ok == 6 and len(sent) == 6
    assert sent[-1][0] >= 60


def test_cli_log_summary(job_dir):
    config = load_config(job_dir / "job.yaml")

    async def transport(prompt):
        return "ok"

    clock = FakeClock()
    summary = asyncio.run(JobRunner(config, transport, clock=clock, sleep=clock.sleep).run())
    result = CliRunner().invoke(cli, ["log", str(summary.log_path)])
    assert result.exit_code == 0
    assert json.loads(result.output)["events"]["done"] == 6
