import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    """Per-process sliding-window limiter keyed by caller IP. No DB round-trip, so it adds no
    measurable latency and can't become a write-contention bottleneck under high throughput —
    deliberately not using the DB-backed AuthRateLimit pattern here for that reason (see the
    "Rate limits" note in README's Security notes for why webhook endpoints don't use that one).
    This is an abuse/flood dampener, not the security boundary (the HMAC/token auth is)."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                raise HTTPException(status_code=429, detail="Too many requests")
            bucket.append(now)


# Limits are generous relative to expected traffic so legitimate bursts are never affected —
# they exist to bound a flood from a single source, not to police normal usage.
service_a_limiter = InMemoryRateLimiter(max_requests=100, window_seconds=1.0)  # NFR target: 20/s sustained
dlr_limiter = InMemoryRateLimiter(max_requests=50, window_seconds=1.0)
reply_limiter = InMemoryRateLimiter(max_requests=20, window_seconds=1.0)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit_service_a(request: Request) -> None:
    service_a_limiter.check(_client_key(request))


def rate_limit_dlr(request: Request) -> None:
    dlr_limiter.check(_client_key(request))


def rate_limit_reply(request: Request) -> None:
    reply_limiter.check(_client_key(request))
