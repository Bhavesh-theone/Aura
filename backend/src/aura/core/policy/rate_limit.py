"""Token buckets (harness categories 1 and 4): a per-key request rate, deterministic and
in-memory. One bucket per key holds up to `capacity` tokens and refills at `per_minute`."""
import threading
import time
from typing import Callable


class TokenBuckets:
    def __init__(self, per_minute: float, capacity: float | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.per_minute = float(per_minute)
        self.capacity = float(capacity if capacity is not None else per_minute)
        self._clock = clock
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tokens, last refill)
        self._lock = threading.Lock()

    def acquire(self, key: str) -> float | None:
        """Take one token. None when allowed; otherwise the seconds until one is free."""
        if self.per_minute <= 0:
            return None  # 0 disables the limit
        rate = self.per_minute / 60.0
        with self._lock:
            now = self._clock()
            tokens, last = self._state.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * rate)
            if tokens >= 1.0:
                self._state[key] = (tokens - 1.0, now)
                return None
            self._state[key] = (tokens, now)
            return (1.0 - tokens) / rate

    def reset(self) -> None:
        with self._lock:
            self._state.clear()
