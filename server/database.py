"""SQLite database for file metadata. Inference results stored as JSON files."""

import sqlite3
from datetime import datetime

DB_PATH = None  # set by app.py on startup


def init_db(path):
    global DB_PATH
    DB_PATH = path
    with sqlite3.connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                storage_name TEXT NOT NULL,
                file_hash TEXT UNIQUE,
                size_bytes INTEGER,
                source TEXT DEFAULT 'hydrophone',
                status TEXT DEFAULT 'uploaded',
                fish_count INTEGER DEFAULT 0,
                total_segments INTEGER DEFAULT 0,
                duration REAL DEFAULT 0,
                fish_ratio REAL DEFAULT 0,
                feeding_level TEXT,
                feeding_amount REAL DEFAULT 0,
                feeding_message TEXT,
                upload_time TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS realtime_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                name TEXT,
                status TEXT NOT NULL,
                chunk_duration REAL DEFAULT 2.0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                stopped_at TEXT,
                last_chunk_at TEXT,
                last_heartbeat_at TEXT,
                client_pending_chunks INTEGER DEFAULT 0,
                client_failed_retryable_chunks INTEGER DEFAULT 0,
                client_failed_conflict_chunks INTEGER DEFAULT 0,
                client_status TEXT DEFAULT 'unknown',
                density_60s REAL DEFAULT 0,
                completeness_60s REAL DEFAULT 0,
                feeding_level TEXT,
                feeding_amount REAL DEFAULT 0,
                feeding_message TEXT,
                feeding_confidence TEXT DEFAULT 'insufficient',
                health_status TEXT DEFAULT 'waiting',
                health_message TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS realtime_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                client_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                duration REAL NOT NULL,
                sample_rate INTEGER,
                storage_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                predicted_class TEXT,
                confidence REAL DEFAULT 0,
                fish_probability REAL DEFAULT 0,
                background_probability REAL DEFAULT 0,
                density_60s REAL DEFAULT 0,
                completeness_60s REAL DEFAULT 0,
                feeding_level TEXT,
                feeding_amount REAL DEFAULT 0,
                feeding_message TEXT,
                feeding_confidence TEXT,
                error_message TEXT,
                UNIQUE(session_id, sequence)
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_realtime_segments_session_captured
            ON realtime_segments(session_id, captured_at)
        """)
        db.commit()


def get_conn():
    return sqlite3.connect(DB_PATH)


def insert_file(original_name, storage_name, file_hash, size_bytes, source="hydrophone"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as db:
        cur = db.execute(
            """INSERT INTO files (original_name, storage_name, file_hash, size_bytes, source, status, upload_time)
               VALUES (?, ?, ?, ?, ?, 'uploaded', ?)""",
            (original_name, storage_name, file_hash, size_bytes, source, now),
        )
        db.commit()
        return cur.lastrowid


def get_file_by_hash(file_hash):
    with get_conn() as db:
        row = db.execute("SELECT id FROM files WHERE file_hash = ?", (file_hash,)).fetchone()
        return row[0] if row else None


def get_file(file_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row) if row else None


def list_files(limit=100, offset=0):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM files ORDER BY upload_time DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]


def update_after_inference(file_id, fish_count, total_segments, duration, fish_ratio, feeding_level, feeding_amount, feeding_message):
    with get_conn() as db:
        db.execute(
            """UPDATE files SET status='analyzed', fish_count=?, total_segments=?, duration=?,
               fish_ratio=?, feeding_level=?, feeding_amount=?, feeding_message=?
               WHERE id=?""",
            (fish_count, total_segments, duration, fish_ratio, feeding_level, feeding_amount, feeding_message, file_id),
        )
        db.commit()


def update_status(file_id, status):
    with get_conn() as db:
        db.execute("UPDATE files SET status=? WHERE id=?", (status, file_id))
        db.commit()


def delete_file(file_id):
    with get_conn() as db:
        db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        db.commit()


def count_files():
    with get_conn() as db:
        return db.execute("SELECT COUNT(*) FROM files").fetchone()[0]


class SequenceConflictError(Exception):
    pass


def _row_to_dict(row):
    return dict(row) if row else None


def create_realtime_session(client_id, name=None, chunk_duration=2.0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as db:
        cur = db.execute(
            """INSERT INTO realtime_sessions
               (client_id, name, status, chunk_duration, created_at, started_at, health_status, health_message)
               VALUES (?, ?, 'running', ?, ?, ?, 'waiting', '等待实时分片')""",
            (client_id, name, chunk_duration, now, now),
        )
        db.commit()
        return cur.lastrowid


def get_realtime_session(session_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM realtime_sessions WHERE id=?", (session_id,)).fetchone()
        return _row_to_dict(row)


def insert_realtime_segment(session_id, client_id, sequence, captured_at, duration, sample_rate, storage_name, sha256):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        existing = db.execute(
            "SELECT * FROM realtime_segments WHERE session_id=? AND sequence=?",
            (session_id, sequence),
        ).fetchone()
        if existing:
            existing_dict = dict(existing)
            if existing_dict["sha256"] != sha256:
                raise SequenceConflictError("sequence already exists with different sha256")
            return {"duplicate": True, "id": existing_dict["id"], "row": existing_dict}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = db.execute(
            """INSERT INTO realtime_segments
               (session_id, client_id, sequence, captured_at, received_at, duration, sample_rate,
                storage_name, sha256, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded')""",
            (session_id, client_id, sequence, captured_at, now, duration, sample_rate, storage_name, sha256),
        )
        db.execute(
            "UPDATE realtime_sessions SET last_chunk_at=?, health_status='receiving', health_message='正在接收实时分片' WHERE id=?",
            (captured_at, session_id),
        )
        db.commit()
        return {"duplicate": False, "id": cur.lastrowid, "row": get_realtime_segment(cur.lastrowid)}


def get_realtime_segment(segment_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM realtime_segments WHERE id=?", (segment_id,)).fetchone()
        return _row_to_dict(row)


def list_realtime_segments(session_id, limit=20):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT * FROM realtime_segments
               WHERE session_id=?
               ORDER BY sequence DESC
               LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
