# tessera

Run batches of prompts against model servers within a token budget, and keep a log of every run.

```bash
tessera run job.yaml          # run a job: pace, send, retry, log, write results
tessera log runs/job-1.jsonl  # summarize a run log
tessera serve job.yaml        # start the job's model servers and wait until they are ready
```

A job file:

```yaml
name: support-triage
model: triage-small
prompts: prompts.jsonl        # one {"id": ..., "prompt": ..., "max_tokens": ...} per line
output: results.jsonl
budget:
  tokens_per_minute: 90000
client:
  endpoint: http://127.0.0.1:8000/v1/completions
  max_in_flight: 8
  max_attempts: 4
  backoff: 0.5
server:                       # optional: start local model servers first
  command: ["python", "-m", "my_model_server", "--port", "{port}"]
  replicas: 2
  base_port: 8000
  startup_timeout: 120
```

## Layout

- `tessera/cli.py`: the command-line interface.
- `tessera/config.py`, `tessera/compat.py`: job files, and the keys older versions used.
- `tessera/jobs.py`: the job runner.
- `tessera/prompts.py`, `tessera/results.py`: reading prompts and writing results.
- `tessera/transport.py`: the HTTP call to a completions endpoint.
- `tessera/pacing/`: keeps the requests within the token budget.
- `tessera/client/`: retries transient errors, with a cap on requests in flight.
- `tessera/serving/`: starts model server processes and waits until they are ready.
- `tessera/runlog/`: the append-only log of a run.

Run the tests with `python -m pytest tests`.
