"""Fixed-window rate limiting, so one client can't flood the service.

With REDIS_URL set, the counters live in Redis and are shared by every replica.
Without it, each process counts on its own (fine for tests and local runs).
"""

import threading
import time


class MemoryRateLimiter:
    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._counts = {}
        self._lock = threading.Lock()

    def allow(self, key):
        window_start = int(time.time()) // self.window
        with self._lock:
            start, count = self._counts.get(key, (window_start, 0))
            if start != window_start:
                start, count = window_start, 0
            count += 1
            self._counts[key] = (start, count)
            return count <= self.limit


class RedisRateLimiter:
    def __init__(self, redis_url, limit, window_seconds):
        import redis

        self.limit = limit
        self.window = window_seconds
        self._redis = redis.Redis.from_url(redis_url)

    def allow(self, key):
        window_start = int(time.time()) // self.window
        redis_key = f"ratelimit:{key}:{window_start}"
        pipe = self._redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, self.window)
        count, _ = pipe.execute()
        return count <= self.limit


def build_rate_limiter(redis_url, limit, window_seconds=60):
    if redis_url:
        return RedisRateLimiter(redis_url, limit, window_seconds)
    return MemoryRateLimiter(limit, window_seconds)
