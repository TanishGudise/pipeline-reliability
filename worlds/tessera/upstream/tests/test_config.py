import warnings

import pytest
from pydantic import ValidationError

from tessera.config import ServerConfig, load_config


def test_relative_paths_are_relative_to_the_job_file(job_dir):
    config = load_config(job_dir / "job.yaml")
    assert config.prompts == job_dir / "prompts.jsonl"
    assert config.output == job_dir / "out" / "results.jsonl"
    assert config.log_dir == job_dir / "runs"
    assert config.budget.tokens_per_minute == 1000
    assert config.client.max_in_flight == 2


def test_old_keys_still_load_with_a_warning(tmp_path):
    (tmp_path / "old.yaml").write_text("name: j\nmodel: m\nprompts: p.jsonl\noutput: o.jsonl\nrpm: 30\nconcurrency: 3\nretries: 2\n")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(tmp_path / "old.yaml")
    assert config.budget.tokens_per_minute == 30_000
    assert config.client.max_in_flight == 3
    assert config.client.max_attempts == 3
    assert sorted(str(w.message).split("'")[1] for w in caught) == ["concurrency", "retries", "rpm"]


def test_invalid_job_files_are_rejected(tmp_path):
    (tmp_path / "bad.yaml").write_text("name: ../escape\nmodel: m\nprompts: p\noutput: o\n")
    with pytest.raises(ValidationError):
        load_config(tmp_path / "bad.yaml")
    (tmp_path / "list.yaml").write_text("- a\n- b\n")
    with pytest.raises(ValueError):
        load_config(tmp_path / "list.yaml")


def test_server_ports_and_commands():
    server = ServerConfig(command=["serve", "--port", "{port}"], replicas=3, base_port=9000)
    assert [server.port(i) for i in range(3)] == [9000, 9001, 9002]
    assert server.command_for(2) == ["serve", "--port", "9002"]
