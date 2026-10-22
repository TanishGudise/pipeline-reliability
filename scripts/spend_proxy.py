"""A local proxy for paid model calls: forwards Anthropic Messages API requests and keeps a spend ledger.

The agent's model client is pointed at http://127.0.0.1:PORT; everything else in the pilot stays on
loopback. The proxy:

- listens on 127.0.0.1 only, accepts only POST /v1/messages for the allowed models, and forwards to
  one fixed upstream (https://api.anthropic.com), adding the API key it reads from a file (the client
  gets a placeholder key, so the real one never appears in Harbor's config or logs);
- reads the token usage of every response (streamed or not) and appends one ledger line per call:
  time, trial tag, model, input / output / cache tokens, cost at the price table below, and the
  running total;
- refuses calls (HTTP 400, without forwarding) once the total reaches the cap minus a margin, or a
  trial's spend reaches the per-trial cap.

Control endpoints (loopback only): POST /_pilot/tag {"trial": "..."} labels the calls that follow;
GET /_pilot/status returns the totals.

usage: python spend_proxy.py --key-file FILE --ledger LEDGER.jsonl [--port 18765] [--cap 40] [--per-trial-cap 8]
"""

from __future__ import annotations

import argparse
import http.client
import json
import ssl
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# $ per million tokens (input, output), list prices; cache writes cost 1.25x input, cache reads 0.1x.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
CACHE_WRITE, CACHE_READ = 1.25, 0.10
MARGIN = 1.00  # stop this far below the cap: one call's cost is only known after it is made


def cost(model: str, usage: dict) -> float:
    pin, pout = PRICES[model]
    return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout
            + usage.get("cache_creation_input_tokens", 0) * pin * CACHE_WRITE
            + usage.get("cache_read_input_tokens", 0) * pin * CACHE_READ) / 1e6


class Ledger:
    def __init__(self, path: str, cap: float, per_trial_cap: float):
        self.path, self.cap, self.per_trial_cap = path, cap, per_trial_cap
        self.lock = threading.Lock()
        self.total, self.by_trial, self.tag = 0.0, {}, ""
        try:  # resume after a restart: the ledger is the record
            with open(path) as f:
                for line in f:
                    row = json.loads(line)
                    self.total = row["total_usd"]
                    self.by_trial[row["trial"]] = self.by_trial.get(row["trial"], 0.0) + row["usd"]
        except FileNotFoundError:
            pass

    def refusal(self) -> str | None:
        with self.lock:
            if self.total >= self.cap - MARGIN:
                return f"spend cap reached: ${self.total:.2f} of ${self.cap:.2f}"
            if self.by_trial.get(self.tag, 0.0) >= self.per_trial_cap:
                return f"per-trial cap reached for {self.tag}: ${self.by_trial[self.tag]:.2f}"
        return None

    def record(self, model: str, usage: dict, status: int, request_id: str, seconds: float) -> None:
        usd = cost(model, usage)
        with self.lock:
            self.total += usd
            self.by_trial[self.tag] = self.by_trial.get(self.tag, 0.0) + usd
            row = {"ts": time.time(), "trial": self.tag, "model": model, "status": status, "request_id": request_id,
                   "seconds": round(seconds, 2), **{k: usage.get(k, 0) for k in ("input_tokens", "output_tokens",
                   "cache_creation_input_tokens", "cache_read_input_tokens")},
                   "usd": round(usd, 6), "total_usd": round(self.total, 6)}
            with open(self.path, "a") as f:
                f.write(json.dumps(row) + "\n")


def merge_usage(into: dict, usage: dict | None) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, int):
            into[k] = v if k != "output_tokens" else max(into.get(k, 0), v)


def make_handler(upstream: str, key: str, ledger: Ledger):
    up = urllib.parse.urlsplit(upstream)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet: the ledger is the log
            pass

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/_pilot/status":
                with ledger.lock:
                    return self._json(200, {"total_usd": ledger.total, "cap": ledger.cap, "tag": ledger.tag,
                                            "by_trial": ledger.by_trial})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            if self.path == "/_pilot/tag":
                with ledger.lock:
                    ledger.tag = json.loads(body or b"{}").get("trial", "")
                return self._json(200, {"tag": ledger.tag})
            if urllib.parse.urlsplit(self.path).path != "/v1/messages":
                return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": self.path}})
            try:
                request = json.loads(body)
            except ValueError:
                return self._json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "bad json"}})
            model = request.get("model", "")
            if model not in PRICES:
                return self._json(400, {"type": "error", "error": {"type": "invalid_request_error",
                                                                    "message": f"model not allowed: {model}"}})
            why = ledger.refusal()
            if why:
                return self._json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": why}})
            headers = {"content-type": "application/json", "x-api-key": key,
                       "anthropic-version": self.headers.get("anthropic-version", "2023-06-01")}
            if self.headers.get("anthropic-beta"):
                headers["anthropic-beta"] = self.headers["anthropic-beta"]
            started = time.time()
            conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
            kwargs = {"context": ssl.create_default_context()} if up.scheme == "https" else {}
            conn = conn_cls(up.hostname, up.port or (443 if up.scheme == "https" else 80), timeout=600, **kwargs)
            usage: dict = {}
            status, request_id = 0, ""
            try:
                conn.request("POST", "/v1/messages", body=body, headers=headers)
                resp = conn.getresponse()
                status, request_id = resp.status, resp.getheader("request-id", "")
                self.send_response(resp.status)
                for name in ("content-type", "request-id", "retry-after"):
                    if resp.getheader(name):
                        self.send_header(name, resp.getheader(name))
                if request.get("stream"):
                    # Relay the event stream as it comes, picking the usage out of message_start / message_delta.
                    self.send_header("transfer-encoding", "chunked")
                    self.end_headers()
                    buf = b""
                    while True:
                        chunk = resp.read1(65536)
                        if not chunk:
                            break
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                        self.wfile.flush()
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            if line.startswith(b"data:"):
                                try:
                                    event = json.loads(line[5:])
                                except ValueError:
                                    continue
                                if event.get("type") == "message_start":
                                    merge_usage(usage, event.get("message", {}).get("usage"))
                                elif event.get("type") == "message_delta":
                                    merge_usage(usage, event.get("usage"))
                    self.wfile.write(b"0\r\n\r\n")
                else:
                    data = resp.read()
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    try:
                        merge_usage(usage, json.loads(data).get("usage"))
                    except ValueError:
                        pass
            finally:
                conn.close()
                ledger.record(model, usage, status, request_id, time.time() - started)

    return Handler


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--key-file", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--port", type=int, default=18765)
    p.add_argument("--cap", type=float, default=40.0)
    p.add_argument("--per-trial-cap", type=float, default=8.0)
    p.add_argument("--upstream", default="https://api.anthropic.com")
    a = p.parse_args()
    with open(a.key_file) as f:
        key = f.read().strip()
    if not key:
        sys.exit("empty key file")
    ledger = Ledger(a.ledger, a.cap, a.per_trial_cap)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.upstream, key, ledger))
    print(f"spend proxy on 127.0.0.1:{a.port} -> {a.upstream}; cap ${a.cap:.2f} (spent ${ledger.total:.2f})", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
