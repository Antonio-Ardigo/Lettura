"""Tiny in-memory stores for short-lived server state (stdlib only).

Lettura is a single-process, single-user local app, so we keep two small
TTL-bounded caches in memory rather than pulling in Redis or a database:

  * ``DocStore``  — the uploaded PDF bytes, keyed by an opaque ``doc_id``, so a
    scanned page can be OCR'd on demand later without re-uploading the whole
    file for every page.
  * ``JobStore``  — the state of a long-running audio export (its progress
    queue and, once finished, the encoded bytes), keyed by a ``job_id``.

Both are bounded by a TTL plus item/byte caps so memory can't grow without
limit. Access is guarded by a lock; OCR/export handlers run in FastAPI's
threadpool, so concurrent access is real.
"""
from __future__ import annotations

import queue
import secrets
import threading
import time
from dataclasses import dataclass, field


class DocStore:
    """Hold uploaded PDF bytes for a short, sliding TTL window."""

    def __init__(
        self,
        *,
        ttl: float = 30 * 60,
        max_items: int = 8,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self._ttl = ttl
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._items: dict[str, list] = {}  # id -> [data, last_used]
        self._lock = threading.Lock()

    def put(self, data: bytes) -> str:
        with self._lock:
            self._evict()
            doc_id = secrets.token_urlsafe(16)
            self._items[doc_id] = [data, time.monotonic()]
            return doc_id

    def get(self, doc_id: str) -> bytes | None:
        with self._lock:
            item = self._items.get(doc_id)
            if item is None:
                return None
            if time.monotonic() - item[1] > self._ttl:
                del self._items[doc_id]
                return None
            item[1] = time.monotonic()  # sliding window
            return item[0]

    def _evict(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._items.items() if now - v[1] > self._ttl]:
            del self._items[key]
        while self._items and (
            len(self._items) >= self._max_items
            or sum(len(v[0]) for v in self._items.values()) > self._max_bytes
        ):
            oldest = min(self._items.items(), key=lambda kv: kv[1][1])[0]
            del self._items[oldest]


@dataclass
class ExportJob:
    """State of one audio-export job, streamed to the browser over SSE."""

    events: queue.Queue = field(default_factory=queue.Queue)
    result: bytes | None = None
    media_type: str | None = None
    filename: str | None = None
    error: str | None = None
    done: bool = False
    created: float = field(default_factory=time.monotonic)


class JobStore:
    """Hold export jobs (progress + finished bytes) for a short TTL."""

    def __init__(self, *, ttl: float = 15 * 60, max_items: int = 16) -> None:
        self._ttl = ttl
        self._max_items = max_items
        self._items: dict[str, ExportJob] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[str, ExportJob]:
        with self._lock:
            self._evict()
            job_id = secrets.token_urlsafe(16)
            job = ExportJob()
            self._items[job_id] = job
            return job_id, job

    def get(self, job_id: str) -> ExportJob | None:
        with self._lock:
            job = self._items.get(job_id)
            if job is None:
                return None
            if time.monotonic() - job.created > self._ttl:
                del self._items[job_id]
                return None
            return job

    def _evict(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._items.items() if now - v.created > self._ttl]:
            del self._items[key]
        # When over the cap, drop the oldest *finished* job first so an export
        # still in progress is never evicted out from under its client.
        while len(self._items) >= self._max_items and self._items:
            finished = {k: v for k, v in self._items.items() if v.done or v.error}
            pool = finished or self._items
            oldest = min(pool.items(), key=lambda kv: kv[1].created)[0]
            del self._items[oldest]
