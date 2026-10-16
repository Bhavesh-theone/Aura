"""The API's rate limiters (in memory, per process). POST /api/jobs: per-user token bucket of
job_submits_per_minute (0 turns it off); over it the request is a 429 with Retry-After."""
import math
import threading

from aura.config import get_settings
from aura.core.domain.errors import RateLimited
from aura.core.policy.rate_limit import TokenBuckets

_lock = threading.Lock()
_submits: TokenBuckets | None = None


def submit_buckets() -> TokenBuckets:
    global _submits
    per_minute = get_settings().job_submits_per_minute
    with _lock:
        if _submits is None or _submits.per_minute != float(per_minute):
            _submits = TokenBuckets(per_minute)
        return _submits


def check_job_submit(username: str) -> None:
    wait = submit_buckets().acquire(username)
    if wait is not None:
        raise RateLimited(f"Too many job submissions: at most "
                          f"{get_settings().job_submits_per_minute} a minute",
                          retry_after_seconds=max(1, math.ceil(wait)))


_exports: TokenBuckets | None = None


def export_buckets() -> TokenBuckets:
    global _exports
    per_minute = get_settings().exports_per_minute
    with _lock:
        if _exports is None or _exports.per_minute != float(per_minute):
            _exports = TokenBuckets(per_minute)
        return _exports


def check_export(username: str) -> None:
    """Deal and deals-list exports: exports_per_minute per user (0 turns it off)."""
    wait = export_buckets().acquire(username)
    if wait is not None:
        raise RateLimited(f"Too many exports: at most {get_settings().exports_per_minute} "
                          f"a minute", retry_after_seconds=max(1, math.ceil(wait)))


def reset() -> None:
    with _lock:
        if _submits is not None:
            _submits.reset()
        if _exports is not None:
            _exports.reset()
