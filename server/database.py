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
                client_last_sequence INTEGER DEFAULT 0,
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


def _duplicate_segment_result(row, sha256):
    row_dict = dict(row)
    if row_dict["sha256"] != sha256:
        raise SequenceConflictError("sequence already exists with different sha256")
    return {"duplicate": True, "id": row_dict["id"], "row": row_dict}


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
            return _duplicate_segment_result(existing, sha256)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur = db.execute(
                """INSERT INTO realtime_segments
                   (session_id, client_id, sequence, captured_at, received_at, duration, sample_rate,
                    storage_name, sha256, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded')""",
                (session_id, client_id, sequence, captured_at, now, duration, sample_rate, storage_name, sha256),
            )
        except sqlite3.IntegrityError:
            existing = db.execute(
                "SELECT * FROM realtime_segments WHERE session_id=? AND sequence=?",
                (session_id, sequence),
            ).fetchone()
            if existing:
                return _duplicate_segment_result(existing, sha256)
            raise

        db.execute(
            """UPDATE realtime_sessions
               SET last_chunk_at=?, health_status='receiving', health_message='正在接收实时分片'
               WHERE id=? AND (last_chunk_at IS NULL OR last_chunk_at < ?)""",
            (captured_at, session_id, captured_at),
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


def update_realtime_segment_analysis(segment_id, predicted_class, confidence, fish_probability,
                                     background_probability, density_60s, completeness_60s, feeding):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT session_id FROM realtime_segments WHERE id=?", (segment_id,)).fetchone()
        if not row:
            return False

        session_id = row["session_id"]
        db.execute(
            """UPDATE realtime_segments
               SET status='analyzed', predicted_class=?, confidence=?, fish_probability=?,
                   background_probability=?, density_60s=?, completeness_60s=?,
                   feeding_level=?, feeding_amount=?, feeding_message=?, feeding_confidence=?, error_message=NULL
               WHERE id=?""",
            (
                predicted_class,
                confidence,
                fish_probability,
                background_probability,
                density_60s,
                completeness_60s,
                feeding.get("level"),
                feeding.get("amount_kg"),
                feeding.get("message"),
                feeding.get("confidence"),
                segment_id,
            ),
        )
        db.execute(
            """UPDATE realtime_sessions
               SET density_60s=?, completeness_60s=?, feeding_level=?, feeding_amount=?,
                   feeding_message=?, feeding_confidence=?, health_status='receiving',
                   health_message='实时监测正常'
               WHERE id=?""",
            (
                density_60s,
                completeness_60s,
                feeding.get("level"),
                feeding.get("amount_kg"),
                feeding.get("message"),
                feeding.get("confidence"),
                session_id,
            ),
        )
        db.commit()
        return True


def update_realtime_segment_error(segment_id, error_message):
    with get_conn() as db:
        db.execute(
            "UPDATE realtime_segments SET status='error', error_message=? WHERE id=?",
            (error_message, segment_id),
        )
        db.commit()


def update_realtime_heartbeat(session_id, client_id, last_sequence, pending_chunks,
                              failed_retryable_chunks, failed_conflict_chunks, client_status, message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as db:
        db.execute(
            """UPDATE realtime_sessions
               SET last_heartbeat_at=?, client_last_sequence=?, client_pending_chunks=?,
                   client_failed_retryable_chunks=?, client_failed_conflict_chunks=?,
                   client_status=?, health_status=?,
                   health_message=?
               WHERE id=? AND client_id=?""",
            (
                now,
                last_sequence,
                pending_chunks,
                failed_retryable_chunks,
                failed_conflict_chunks,
                client_status,
                client_status,
                message,
                session_id,
                client_id,
            ),
        )
        db.commit()
        return db.total_changes > 0
