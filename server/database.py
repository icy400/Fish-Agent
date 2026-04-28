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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as db:
        db.execute(
            """UPDATE files SET status='analyzed', fish_count=?, total_segments=?, duration=?,
               fish_ratio=?, feeding_level=?, feeding_amount=?, feeding_message=?, upload_time=upload_time""",
            (fish_count, total_segments, duration, fish_ratio, feeding_level, feeding_amount, feeding_message),
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
