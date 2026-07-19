import time

from app.core.rate_limiter import LoginRateLimiter


def test_allows_attempts_under_the_limit():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
    key = "testuser:127.0.0.1"

    for _ in range(2):
        locked, _ = limiter.check(key)
        assert locked is False
        limiter.record_failure(key)

    locked, _ = limiter.check(key)
    assert locked is False  # still only 2 failures, limit is 3


def test_locks_out_after_max_attempts():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
    key = "testuser:127.0.0.1"

    for _ in range(3):
        limiter.record_failure(key)

    locked, remaining = limiter.check(key)
    assert locked is True
    assert remaining > 0


def test_successful_login_resets_the_counter():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
    key = "testuser:127.0.0.1"

    limiter.record_failure(key)
    limiter.record_failure(key)
    limiter.record_success(key)

    locked, _ = limiter.check(key)
    assert locked is False

    # Should now take a fresh 3 failures to lock out again, not just 1 more
    limiter.record_failure(key)
    locked, _ = limiter.check(key)
    assert locked is False


def test_lockout_expires_after_lockout_window():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, lockout_seconds=1)
    key = "testuser:127.0.0.1"

    limiter.record_failure(key)
    limiter.record_failure(key)
    locked, _ = limiter.check(key)
    assert locked is True

    time.sleep(1.1)
    locked, _ = limiter.check(key)
    assert locked is False


def test_different_keys_are_tracked_independently():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, lockout_seconds=60)

    limiter.record_failure("alice:127.0.0.1")
    limiter.record_failure("alice:127.0.0.1")
    alice_locked, _ = limiter.check("alice:127.0.0.1")
    bob_locked, _ = limiter.check("bob:127.0.0.1")

    assert alice_locked is True
    assert bob_locked is False
