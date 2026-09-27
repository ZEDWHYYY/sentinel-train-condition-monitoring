"""Run-keyed persistence: SQLite metadata + per-run file storage.

Every run's inputs, results, reviews and exports are isolated. Result payloads
are immutable JSON files; reviews are append-only revisions."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(os.environ.get("SENTINEL_STORE", Path(__file__).resolve().parent / "run_store"))
DB_PATH = STORE / "sentinel.db"
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, subsystem TEXT, purpose TEXT NOT NULL DEFAULT 'analysis', state TEXT NOT NULL,
  created TEXT NOT NULL, updated TEXT NOT NULL, stage TEXT, files_done INTEGER DEFAULT 0, files_total INTEGER DEFAULT 0,
  error TEXT, versions TEXT, idempotency_key TEXT, cancel_requested INTEGER DEFAULT 0, parent_id TEXT, label TEXT
);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, original_name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER,
  stored_path TEXT NOT NULL, source_kind TEXT NOT NULL, subsystem TEXT, recognition TEXT, sheet TEXT,
  status TEXT NOT NULL, error TEXT, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, file_id TEXT NOT NULL, subsystem TEXT NOT NULL, available INTEGER,
  payload_path TEXT NOT NULL, headline TEXT, review_count INTEGER, quality_state TEXT, model_version TEXT,
  repeat_key TEXT, repeat_of TEXT, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, result_id TEXT NOT NULL, item_id TEXT NOT NULL, kind TEXT NOT NULL, assessment TEXT,
  note TEXT, reviewer TEXT, reason TEXT, revision INTEGER NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL, path TEXT, filename TEXT, media_type TEXT,
  manifest TEXT, errors TEXT, run_ids TEXT
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT, updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS files_run ON files(run_id);
CREATE INDEX IF NOT EXISTS results_run ON results(run_id);
CREATE INDEX IF NOT EXISTS reviews_result ON reviews(result_id);
CREATE INDEX IF NOT EXISTS results_repeat ON results(repeat_key);
"""

JSON_COLS = {"versions", "recognition", "error", "manifest", "errors", "run_ids"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def init() -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(reviews)").fetchall()}
        for col in ("assignee", "due"):  # lifecycle hand-off fields added after the first release
            if col not in cols:
                c.execute(f"ALTER TABLE reviews ADD COLUMN {col} TEXT")


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if d[k] is not None:
            d[k] = json.loads(d[k])
    return d


def _enc(v):
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def insert(table: str, **fields) -> dict:
    cols = ",".join(fields)
    q = ",".join("?" for _ in fields)
    with conn() as c:
        c.execute(f"INSERT INTO {table} ({cols}) VALUES ({q})", [_enc(v) for v in fields.values()])
    return fields


def update(table: str, id_: str, **fields) -> None:
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id=?", [_enc(v) for v in fields.values()] + [id_])


def get(table: str, id_: str) -> dict | None:
    with conn() as c:
        return _row(c.execute(f"SELECT * FROM {table} WHERE id=?", (id_,)).fetchone())


def select(sql: str, args=()) -> list[dict]:
    with conn() as c:
        return [_row(r) for r in c.execute(sql, args).fetchall()]


def run_dir(run_id: str) -> Path:
    p = STORE / "runs" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_payload(run_id: str, result_id: str, payload: dict) -> Path:
    p = run_dir(run_id) / "results" / f"{result_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def read_payload(result: dict) -> dict:
    return json.loads(Path(result["payload_path"]).read_text(encoding="utf-8"))


def add_review(result_id: str, item_id: str, kind: str, expected_revision: int | None, **fields) -> dict:
    """Append-only revision with optimistic concurrency on (result, item, kind)."""
    with _lock:
        with conn() as c:
            cur = c.execute("SELECT MAX(revision) FROM reviews WHERE result_id=? AND item_id=? AND kind=?",
                            (result_id, item_id, kind)).fetchone()[0] or 0
            if expected_revision is not None and expected_revision != cur:
                raise ValueError(f"revision conflict: expected {expected_revision}, current {cur}")
            rec = {"id": new_id("rev"), "result_id": result_id, "item_id": item_id, "kind": kind,
                   "revision": cur + 1, "created": now(), **fields}
            cols = ",".join(rec)
            c.execute(f"INSERT INTO reviews ({cols}) VALUES ({','.join('?' for _ in rec)})", list(rec.values()))
    return rec


def get_setting(key: str):
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r and r[0] is not None else None


def set_setting(key: str, value) -> None:
    with conn() as c:
        c.execute("INSERT INTO settings (key, value, updated) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                  (key, json.dumps(value, ensure_ascii=False), now()))
