"""Per-client prediction history in SQLite.

There are no accounts. The browser keeps a random client id (UUID) and sends it as ``X-Client-Id``; only a salted SHA-256
hash is stored, so one client can only list/delete rows that match its own id. No IP address, name or other personal data
is stored: only the inputs the user typed into the estimator, the output, a timestamp and the model version.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_ID = re.compile(r"^[A-Za-z0-9\-]{16,64}$")


class HistoryStore:
    def __init__(self, path: Path, salt: str, limit: int = 100):
        self.path, self.salt, self.limit = Path(path), salt, limit
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, client_hash TEXT NOT NULL, created_utc TEXT NOT NULL,
                model_version TEXT NOT NULL, inputs_json TEXT NOT NULL, estimate_inr REAL NOT NULL, low_inr REAL, high_inr REAL)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_client ON predictions(client_hash, id)")

    @contextlib.contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def valid_client_id(value: str | None) -> bool:
        return bool(value and _ID.match(value))

    def _hash(self, client_id: str) -> str:
        return hashlib.sha256((self.salt + client_id).encode()).hexdigest()

    def add(self, client_id: str, model_version: str, inputs: dict, estimate: float, low: float | None, high: float | None) -> None:
        h = self._hash(client_id)
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO predictions(client_hash, created_utc, model_version, inputs_json, estimate_inr, low_inr, high_inr) VALUES (?,?,?,?,?,?,?)",
                      (h, datetime.now(timezone.utc).isoformat(timespec="seconds"), model_version, json.dumps(inputs), estimate, low, high))
            c.execute("DELETE FROM predictions WHERE client_hash=? AND id NOT IN (SELECT id FROM predictions WHERE client_hash=? ORDER BY id DESC LIMIT ?)",
                      (h, h, self.limit))

    def list(self, client_id: str) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT id, created_utc, model_version, inputs_json, estimate_inr, low_inr, high_inr FROM predictions "
                             "WHERE client_hash=? ORDER BY id DESC LIMIT ?", (self._hash(client_id), self.limit)).fetchall()
        return [{"id": r[0], "created_utc": r[1], "model_version": r[2], "inputs": json.loads(r[3]), "estimated_price_inr": r[4], "low_inr": r[5], "high_inr": r[6]} for r in rows]

    def clear(self, client_id: str) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM predictions WHERE client_hash=?", (self._hash(client_id),)).rowcount

    def close(self) -> None:
        pass
