import threading
import time
from typing import Any


class LRUCache:
    def __init__(self, max_size: int = 100, ttl_seconds: float = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        timestamp, value = entry
        if time.time() - timestamp > self._ttl:
            del self._store[key]
            self._misses += 1
            return None

        self._hits += 1
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self._max_size:
            oldest_key = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest_key]

        self._store[key] = (time.time(), value)

    def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    def clear(self) -> None:
        self._store.clear()

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total

    @property
    def size(self) -> int:
        return len(self._store)


def batch_get(cache: LRUCache, keys: list[str]) -> dict[str, Any]:
    results = {}
    for key in keys:
        val = cache.get(key)
        if val is not None:
            results[key] = val
    return results


def cached_fetch(cache: LRUCache, key: str, fetcher: Any) -> Any:
    result = cache.get(key)
    if result:
        return result

    data = fetcher()
    cache.set(key, data)
    return data


class AsyncBatcher:
    def __init__(self, batch_size: int = 10, flush_interval: float = 1.0):
        self._buffer: list[Any] = []
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._callbacks: list[Any] = []
        self._running = False
        self._thread: threading.Thread | None = None

    def add(self, item: Any) -> None:
        self._buffer.append(item)
        if len(self._buffer) >= self._batch_size:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer
        self._buffer = []
        for cb in self._callbacks:
            cb(batch)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join()
        self._flush()

    def _run_loop(self) -> None:
        while self._running:
            time.sleep(self._flush_interval)
            self._flush()

    def on_batch(self, callback: Any) -> None:
        self._callbacks.append(callback)
