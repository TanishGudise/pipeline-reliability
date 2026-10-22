"""The HTTP call to an OpenAI-style completions endpoint."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from .client import TransientError

RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


class RequestFailed(Exception):
    """The endpoint rejected the request in a way that retrying won't fix."""


def _post(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in RETRY_STATUSES:
            raise TransientError(f"HTTP {e.code} from {url}") from None
        raise RequestFailed(f"HTTP {e.code} from {url}: {e.read()[:200]!r}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise TransientError(f"{url}: {e}") from None


class HttpTransport:
    """Sends one completion request; network errors and retryable statuses raise TransientError."""

    def __init__(self, endpoint: str, model: str, timeout: float = 60.0):
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    async def __call__(self, prompt) -> str:
        payload = {"model": self.model, "prompt": prompt.prompt, "max_tokens": prompt.max_tokens}
        body = await asyncio.to_thread(_post, self.endpoint, payload, self.timeout)
        try:
            return body["choices"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise RequestFailed(f"unexpected response from {self.endpoint}: {str(body)[:200]}") from None
