"""In-memory runs: each run is an agent working in a thread, plus the events it has logged so far."""

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

RUN_TTL_S = 3600
MAX_RUNS = 200


@dataclass
class Run:
    id: str
    source: str  # "NYC demo · 41 transactions"
    live: bool
    created: float = field(default_factory=time.time)
    events: list[dict] = field(default_factory=list)
    report: dict | None = None
    error: str | None = None
    done: bool = False
    _cond: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def push(self, event: dict) -> None:
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    def finish(self, report: dict) -> None:
        with self._cond:
            self.report, self.done = report, True
            self._cond.notify_all()

    def fail(self, message: str) -> None:
        with self._cond:
            self.error, self.done = message, True
            self._cond.notify_all()

    def since(self, index: int) -> tuple[list[dict], bool]:
        with self._cond:
            return self.events[index:], self.done


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def create(self, source: str, live: bool) -> Run:
        run = Run(id=uuid.uuid4().hex[:12], source=source, live=live)
        with self._lock:
            self._prune()
            self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def _prune(self) -> None:
        cutoff = time.time() - RUN_TTL_S
        for rid in [r for r, run in self._runs.items() if run.created < cutoff]:
            del self._runs[rid]
        while len(self._runs) >= MAX_RUNS:
            del self._runs[next(iter(self._runs))]


class RateLimiter:
    """Sliding window per client IP."""

    def __init__(self, max_hits: int, window_s: float) -> None:
        self.max_hits, self.window_s = max_hits, window_s
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, ip: str) -> float:
        """Records a hit and returns 0, or returns seconds to wait (no hit recorded)."""
        now = time.time()
        with self._lock:
            hits = self._hits.setdefault(ip, deque())
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            if len(hits) >= self.max_hits:
                return hits[0] + self.window_s - now
            hits.append(now)
            return 0.0
