"""
Lightweight in-memory rate limiter for the login endpoint.

Tracks failed attempts per (username, client IP) pair within a sliding
window, and temporarily locks out further attempts once a threshold is
crossed. This is deliberately simple — no Redis, no external service —
appropriate for a single-process deployment.

LIMITATION (worth knowing, not hiding): because this is in-process
memory, it resets on restart and does NOT share state across multiple
server instances/workers. A production multi-instance deployment would
move this to a shared store (Redis) so the limit applies globally
rather than per-process. For a portfolio/demo-scale single-instance
deployment, this in-memory approach is a legitimate, correct choice.
"""
import time
import threading
from collections import defaultdict
from typing import Tuple


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300, lockout_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._attempts[key] if now - t < self.window_seconds]
        self._attempts[key] = recent
        return recent

    def check(self, key: str) -> Tuple[bool, int]:
        """Returns (is_locked_out, seconds_remaining)."""
        with self._lock:
            now = time.time()
            attempts = self._prune(key, now)
            if len(attempts) >= self.max_attempts:
                oldest = attempts[0]
                elapsed = now - oldest
                if elapsed < self.lockout_seconds:
                    # Use ceil (via int(...) + 1 guard) so a fractional
                    # remaining time never truncates to 0 while still locked.
                    remaining = max(1, int(self.lockout_seconds - elapsed + 0.999))
                    return True, remaining
                # Lockout window has expired — clear and allow through
                self._attempts[key] = []
            return False, 0

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._attempts[key].append(time.time())

    def record_success(self, key: str) -> None:
        with self._lock:
            self._attempts[key] = []


# One shared instance for the whole app process.
login_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300, lockout_seconds=300)
