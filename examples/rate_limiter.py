import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class RateLimitConfig:
    max_requests: int = 100
    window_seconds: float = 60.0
    burst_limit: int = 10


@dataclass
class RateLimiter:
    config: RateLimitConfig = field(default_factory=RateLimitConfig)
    _windows: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def allow(self, client_id: str) -> bool:
        now = time.time()
        cutoff = now - self.config.window_seconds
        timestamps = self._windows[client_id]

        self._windows[client_id] = [t for t in timestamps if t > cutoff]

        if len(self._windows[client_id]) >= self.config.max_requests:
            return False

        recent = [t for t in self._windows[client_id] if t > now - 1.0]
        if len(recent) >= self.config.burst_limit:
            return False

        self._windows[client_id].append(now)
        return True

    def remaining(self, client_id: str) -> int:
        now = time.time()
        cutoff = now - self.config.window_seconds
        active = [t for t in self._windows[client_id] if t > cutoff]
        return max(0, self.config.max_requests - len(active))

    def reset_time(self, client_id: str) -> float:
        timestamps = self._windows[client_id]
        if not timestamps:
            return 0.0
        oldest = min(timestamps)
        return oldest + self.config.window_seconds

    def cleanup(self) -> int:
        now = time.time()
        cutoff = now - self.config.window_seconds
        removed = 0
        for client_id in list(self._windows.keys()):
            self._windows[client_id] = [
                t for t in self._windows[client_id] if t > cutoff
            ]
            if not self._windows[client_id]:
                del self._windows[client_id]
                removed += 1
        return removed


class SlidingWindowCounter:
    def __init__(self, window_seconds: float = 60.0):
        self._window = window_seconds
        self._current_count = 0
        self._previous_count = 0
        self._current_start = time.time()

    def increment(self) -> None:
        self._rotate()
        self._current_count += 1

    def count(self) -> float:
        self._rotate()
        elapsed = time.time() - self._current_start
        weight = elapsed / self._window
        return self._previous_count * (1 - weight) + self._current_count

    def _rotate(self) -> None:
        now = time.time()
        elapsed = now - self._current_start
        if elapsed >= self._window:
            self._previous_count = self._current_count
            self._current_count = 0
            self._current_start = now
