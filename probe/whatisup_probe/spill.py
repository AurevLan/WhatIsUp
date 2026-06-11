"""Disk spill buffer for check results.

When the central API is unreachable (or the in-memory queue overflows) the
reporter persists results here as JSONL instead of dropping them, then
re-sends them once the API is back. Bounded in size so a long outage cannot
fill the disk: when the file grows past the cap, the oldest entries are
discarded first.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_MAX_ENTRIES = 5000
# Compact the file when it grows past this size (~ max_entries * typical line)
_COMPACT_THRESHOLD_BYTES = 4 * 1024 * 1024


class DiskSpill:
    """Append-only JSONL buffer with FIFO drain and oldest-first eviction.

    Thread-safe via a lock; file I/O is small (one JSON line per result) so
    calling it from the event loop is acceptable.
    """

    def __init__(self, path: str | None = None, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._path = path or os.path.join(tempfile.gettempdir(), "whatisup_probe_spill.jsonl")
        self._max_entries = max_entries
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    def append(self, payload: dict) -> None:
        """Persist one result payload. Never raises (best-effort)."""
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload) + "\n")
                if os.path.getsize(self._path) > _COMPACT_THRESHOLD_BYTES:
                    self._compact_locked()
            except OSError as exc:
                logger.warning("spill_append_failed", error=str(exc))

    def pop_batch(self, n: int) -> list[dict]:
        """Remove and return up to *n* oldest payloads. Never raises."""
        with self._lock:
            try:
                if not os.path.exists(self._path):
                    return []
                with open(self._path, encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as exc:
                logger.warning("spill_read_failed", error=str(exc))
                return []

            head, tail = lines[:n], lines[n:]
            payloads: list[dict] = []
            for line in head:
                try:
                    payloads.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # corrupted line (partial write) — skip it

            try:
                self._rewrite_locked(tail)
            except OSError as exc:
                logger.warning("spill_rewrite_failed", error=str(exc))
            return payloads

    def pending_count(self) -> int:
        """Approximate number of buffered entries (for logs/health)."""
        with self._lock:
            try:
                if not os.path.exists(self._path):
                    return 0
                with open(self._path, encoding="utf-8") as f:
                    return sum(1 for _ in f)
            except OSError:
                return 0

    def _compact_locked(self) -> None:
        """Keep only the newest *max_entries* lines (drop oldest first)."""
        with open(self._path, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > self._max_entries:
            dropped = len(lines) - self._max_entries
            logger.warning("spill_evicted_oldest", dropped=dropped)
            self._rewrite_locked(lines[-self._max_entries :])

    def _rewrite_locked(self, lines: list[str]) -> None:
        """Atomically replace the spill file content."""
        if not lines:
            try:
                os.remove(self._path)
            except FileNotFoundError:
                pass
            return
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(tmp_path, self._path)
