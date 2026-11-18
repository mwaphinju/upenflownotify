from app.ratelimit import InMemoryRateLimiter


def test_allows_requests_under_the_limit():
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")


def test_rejects_requests_over_the_limit():
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    try:
        limiter.check("1.2.3.4")
        assert False, "expected HTTPException"
    except Exception as error:
        assert getattr(error, "status_code", None) == 429


def test_limits_are_tracked_independently_per_key():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")


def test_old_hits_expire_out_of_the_window():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=0.05)
    limiter.check("1.2.3.4")
    import time

    time.sleep(0.1)
    limiter.check("1.2.3.4")
