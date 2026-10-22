import json

import pytest


@pytest.fixture
def job_dir(tmp_path):
    """A directory with a prompts file and a job file pointing at it."""
    prompts = [{"id": f"p{i}", "prompt": f"Summarize ticket {i}: " + "words " * (i * 3), "max_tokens": 50} for i in range(6)]
    (tmp_path / "prompts.jsonl").write_text("".join(json.dumps(p) + "\n" for p in prompts))
    (tmp_path / "job.yaml").write_text(
        "name: triage\nmodel: small\nprompts: prompts.jsonl\noutput: out/results.jsonl\nlog_dir: runs\n"
        "budget:\n  tokens_per_minute: 1000\nclient:\n  max_in_flight: 2\n  max_attempts: 3\n  backoff: 0.01\n"
    )
    return tmp_path
