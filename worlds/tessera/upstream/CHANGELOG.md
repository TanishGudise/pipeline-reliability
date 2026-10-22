# Changelog

## 0.4.2
- `tessera log` prints per-status counts.
- The job runner closes the run log when the log supports it.

## 0.4.0
- Job files are validated with pydantic. Old keys (`rpm`, `concurrency`, `retries`) still load, with a
  deprecation warning; see `tessera/compat.py`.
- Model servers can be started with several replicas (`server.replicas`).

## 0.3.0
- Token budget pacing (`budget.tokens_per_minute`).
- Results are written as JSON Lines or CSV, by the output file's extension.
