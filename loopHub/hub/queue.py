"""SQLite job queue. One table; workers poll by job type.

Re-entry guard (design doc guardrail 5) lives here: enqueue() refuses a job
when the same (job_type, story_id) already has a pending/running job.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    story_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending|running|done|failed|duplicate
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, job_type);
"""


class JobQueue:
    def __init__(self, db_path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def enqueue(self, job_type: str, story_id: int, payload: dict[str, Any]) -> int | None:
        """Insert a job; return its id, or None if an active duplicate exists."""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "SELECT id FROM jobs WHERE job_type=? AND story_id=? "
                "AND status IN ('pending','running')",
                (job_type, story_id),
            )
            if cur.fetchone():
                return None
            cur = self._conn.execute(
                "INSERT INTO jobs (job_type, story_id, payload, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (job_type, story_id, json.dumps(payload), now, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def claim(self, job_type: str) -> dict[str, Any] | None:
        """Atomically claim the oldest pending job of a type."""
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_type=? AND status='pending' "
                "ORDER BY id LIMIT 1",
                (job_type,),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE jobs SET status='running', updated_at=? WHERE id=?",
                (now, row["id"]),
            )
            self._conn.commit()
        job = dict(row)
        job["payload"] = json.loads(job["payload"])
        return job

    def finish(self, job_id: int, ok: bool, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
                ("done" if ok else "failed", error, time.time(), job_id),
            )
            self._conn.commit()

    def has_active(self, story_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM jobs WHERE story_id=? AND status IN ('pending','running')",
                (story_id,),
            ).fetchone()
        return row is not None
