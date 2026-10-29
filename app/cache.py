"""Thread-safe in-memory cache shared by concurrent runs (web) or used per run (CLI)."""

import threading


class Cache:
    def __init__(self) -> None:
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key) -> tuple[bool, object]:
        with self._lock:
            if key in self._data:
                return True, self._data[key]
            return False, None

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = value

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
