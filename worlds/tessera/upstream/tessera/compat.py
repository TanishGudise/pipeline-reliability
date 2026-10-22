"""Keys that older versions of tessera used in job files.

Kept so that existing job files still load; each one warns once. Remove in 0.6.
"""

import warnings

# old key -> (section, new key, how to convert the value)
_RENAMED = {
    "rpm": ("budget", "tokens_per_minute", lambda v: int(v) * 1000),  # 0.2 counted requests; assume ~1k tokens each
    "concurrency": ("client", "max_in_flight", int),
    "retries": ("client", "max_attempts", lambda v: int(v) + 1),
    "url": ("client", "endpoint", str),
}


def upgrade(raw: dict) -> dict:
    """Move old top-level keys to where the current schema expects them."""
    raw = dict(raw)
    for old, (section, new, convert) in _RENAMED.items():
        if old not in raw:
            continue
        warnings.warn(f"job file key {old!r} is deprecated; use {section}.{new}", DeprecationWarning, stacklevel=3)
        value = raw.pop(old)
        target = dict(raw.get(section) or {})
        target.setdefault(new, convert(value))
        raw[section] = target
    return raw
