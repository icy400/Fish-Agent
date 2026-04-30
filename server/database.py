"""SQLite database for file metadata. Inference results stored as JSON files."""

import json
import sqlite3
import uuid
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
                queue_key TEXT,
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
            CREATE TABLE IF NOT EXISTS realtime_clients (
                client_id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT DEFAULT 'offline',
                current_session_id INTEGER,
                last_heartbeat_at TEXT,
                last_seen_at TEXT,
                agent_version TEXT,
                sample_rate INTEGER,
                chunk_duration REAL,
                pending_chunks INTEGER DEFAULT 0,
                failed_retryable_chunks INTEGER DEFAULT 0,
                failed_conflict_chunks INTEGER DEFAULT 0,
                last_sequence INTEGER DEFAULT 0,
                message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS realtime_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                session_id INTEGER,
                command_type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL,
                acked_at TEXT,
                running_at TEXT,
                completed_at TEXT,
                error_message TEXT
            )
        """)
        realtime_session_columns = {
            row[1] for row in db.execute("PRAGMA table_info(realtime_sessions)").fetchall()
        }
        if "client_last_sequence" not in realtime_session_columns:
            db.execute(
                "ALTER TABLE realtime_sessions ADD COLUMN client_last_sequence INTEGER DEFAULT 0"
            )
        if "queue_key" not in realtime_session_columns:
            db.execute(
                "ALTER TABLE realtime_sessions ADD COLUMN queue_key TEXT"
            )
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_realtime_segments_session_captured
            ON realtime_segments(session_id, captured_at)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_realtime_commands_client_status
            ON realtime_commands(client_id, status, created_at)
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


class RealtimeSessionNotStoppedError(Exception):
    pass


ACTIVE_COMMAND_STATUSES = ("pending", "acked", "running")
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _now():
    return datetime.now().strftime(DATETIME_FORMAT)


def _row_to_dict(row):
    return dict(row) if row else None


def _duplicate_segment_result(row, sha256):
    row_dict = dict(row)
    if row_dict["sha256"] != sha256:
        raise SequenceConflictError("sequence already exists with different sha256")
    return {"duplicate": True, "id": row_dict["id"], "row": row_dict}


def create_realtime_session(client_id, name=None, chunk_duration=2.0, queue_key=None):
    now = _now()
    with get_conn() as db:
        cur = db.execute(
            """INSERT INTO realtime_sessions
               (client_id, queue_key, name, status, chunk_duration, created_at, started_at,
                health_status, health_message)
               VALUES (?, ?, ?, 'running', ?, ?, ?, 'waiting', '等待实时分片')""",
            (client_id, queue_key, name, chunk_duration, now, now),
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

        now = _now()
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


def list_realtime_sessions_for_client(client_id, limit=20):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT * FROM realtime_sessions
               WHERE client_id=?
               ORDER BY id DESC
               LIMIT ?""",
            (client_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


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
    now = _now()
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


def stop_realtime_session(session_id):
    now = _now()
    with get_conn() as db:
        db.execute(
            """UPDATE realtime_sessions
               SET status='stopped', stopped_at=?, health_status='stopped',
                   health_message='实时监测已停止'
               WHERE id=?""",
            (now, session_id),
        )
        db.commit()
    return get_realtime_session(session_id)


def _client_row_to_dict(row, online_seconds=10):
    data = _row_to_dict(row)
    if not data:
        return None
    data["online"] = _is_recent(data.get("last_heartbeat_at"), online_seconds)
    if not data["online"]:
        data["effective_status"] = "offline"
    else:
        data["effective_status"] = data.get("status") or "idle"
    return data


def _is_recent(value, online_seconds):
    if not value:
        return False
    try:
        delta = datetime.now() - datetime.strptime(value, DATETIME_FORMAT)
    except ValueError:
        return False
    return delta.total_seconds() <= online_seconds


def _upsert_realtime_client_on_conn(db, client_id, name=None, status="idle", current_session_id=None,
                                    agent_version=None, sample_rate=None, chunk_duration=None,
                                    last_sequence=0, pending_chunks=0, failed_retryable_chunks=0,
                                    failed_conflict_chunks=0, message="", touch_heartbeat=True):
    now = _now()
    heartbeat_at = now if touch_heartbeat else None
    db.execute(
        """INSERT INTO realtime_clients
           (client_id, name, status, current_session_id, last_heartbeat_at, last_seen_at,
            agent_version, sample_rate, chunk_duration, pending_chunks,
            failed_retryable_chunks, failed_conflict_chunks, last_sequence, message,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(client_id) DO UPDATE SET
             name=COALESCE(excluded.name, realtime_clients.name),
             status=excluded.status,
             current_session_id=excluded.current_session_id,
             last_heartbeat_at=COALESCE(excluded.last_heartbeat_at, realtime_clients.last_heartbeat_at),
             last_seen_at=COALESCE(excluded.last_seen_at, realtime_clients.last_seen_at),
             agent_version=COALESCE(excluded.agent_version, realtime_clients.agent_version),
             sample_rate=COALESCE(excluded.sample_rate, realtime_clients.sample_rate),
             chunk_duration=COALESCE(excluded.chunk_duration, realtime_clients.chunk_duration),
             pending_chunks=excluded.pending_chunks,
             failed_retryable_chunks=excluded.failed_retryable_chunks,
             failed_conflict_chunks=excluded.failed_conflict_chunks,
             last_sequence=excluded.last_sequence,
             message=excluded.message,
             updated_at=excluded.updated_at""",
        (
            client_id,
            name,
            status,
            current_session_id,
            heartbeat_at,
            heartbeat_at,
            agent_version,
            sample_rate,
            chunk_duration,
            pending_chunks,
            failed_retryable_chunks,
            failed_conflict_chunks,
            last_sequence,
            message,
            now,
            now,
        ),
    )


def upsert_realtime_client(client_id, name=None, status="idle", current_session_id=None,
                           agent_version=None, sample_rate=None, chunk_duration=None,
                           last_sequence=0, pending_chunks=0, failed_retryable_chunks=0,
                           failed_conflict_chunks=0, message=""):
    with get_conn() as db:
        _upsert_realtime_client_on_conn(
            db,
            client_id=client_id,
            name=name,
            status=status,
            current_session_id=current_session_id,
            agent_version=agent_version,
            sample_rate=sample_rate,
            chunk_duration=chunk_duration,
            last_sequence=last_sequence,
            pending_chunks=pending_chunks,
            failed_retryable_chunks=failed_retryable_chunks,
            failed_conflict_chunks=failed_conflict_chunks,
            message=message,
        )
        db.commit()
    return get_realtime_client(client_id)


def get_realtime_client(client_id, online_seconds=10):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM realtime_clients WHERE client_id=?",
            (client_id,),
        ).fetchone()
        return _client_row_to_dict(row, online_seconds=online_seconds)


def list_realtime_clients(online_seconds=10):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM realtime_clients ORDER BY client_id"
        ).fetchall()
        return [_client_row_to_dict(row, online_seconds=online_seconds) for row in rows]


def _active_session_for_client(db, client_id):
    row = db.execute(
        """SELECT * FROM realtime_sessions
           WHERE client_id=? AND status='running'
           ORDER BY id DESC LIMIT 1""",
        (client_id,),
    ).fetchone()
    return row


def _active_command_for_client(db, client_id, command_type=None):
    sql = f"""SELECT * FROM realtime_commands
              WHERE client_id=? AND status IN ({','.join('?' for _ in ACTIVE_COMMAND_STATUSES)})"""
    params = [client_id, *ACTIVE_COMMAND_STATUSES]
    if command_type:
        sql += " AND command_type=?"
        params.append(command_type)
    sql += " ORDER BY id ASC LIMIT 1"
    return db.execute(sql, params).fetchone()


def _insert_realtime_command(db, client_id, session_id, command_type, payload):
    now = _now()
    cur = db.execute(
        """INSERT INTO realtime_commands
           (client_id, session_id, command_type, status, payload, created_at)
           VALUES (?, ?, ?, 'pending', ?, ?)""",
        (client_id, session_id, command_type, json.dumps(payload or {}, ensure_ascii=False), now),
    )
    return cur.lastrowid


def _command_response(command_id, session_id, status, client_id):
    return {
        "client_id": client_id,
        "session_id": session_id,
        "command_id": command_id,
        "command_status": status,
    }


def enqueue_start_capture_command(client_id, session_name=None, chunk_duration=2.0):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        now = _now()
        existing_session = _active_session_for_client(db, client_id)
        if existing_session:
            command = _active_command_for_client(db, client_id, "start_capture")
            status = command["status"] if command else "already_running"
            command_id = command["id"] if command else None
            db.commit()
            return _command_response(command_id, existing_session["id"], status, client_id)

        queue_key = uuid.uuid4().hex
        cur = db.execute(
            """INSERT INTO realtime_sessions
               (client_id, queue_key, name, status, chunk_duration, created_at, started_at,
                health_status, health_message)
               VALUES (?, ?, ?, 'running', ?, ?, ?, 'waiting', '等待采集端执行开始命令')""",
            (client_id, queue_key, session_name, chunk_duration, now, now),
        )
        session_id = cur.lastrowid
        _upsert_realtime_client_on_conn(
            db,
            client_id=client_id,
            name=session_name,
            status="idle",
            current_session_id=session_id,
            chunk_duration=chunk_duration,
            message="等待采集端执行开始命令",
            touch_heartbeat=False,
        )
        command_id = _insert_realtime_command(
            db,
            client_id=client_id,
            session_id=session_id,
            command_type="start_capture",
            payload={
                "session_name": session_name,
                "chunk_duration": chunk_duration,
                "queue_key": queue_key,
                "next_sequence": 1,
            },
        )
        db.commit()
        return _command_response(command_id, session_id, "pending", client_id)


def enqueue_stop_capture_command(client_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        active_start = _active_command_for_client(db, client_id, "start_capture")
        if active_start and active_start["status"] == "pending":
            db.execute(
                "UPDATE realtime_commands SET status='cancelled', completed_at=? WHERE id=?",
                (_now(), active_start["id"]),
            )
            if active_start["session_id"]:
                db.execute(
                    """UPDATE realtime_sessions
                       SET status='stopped', stopped_at=?, health_status='stopped',
                           health_message='开始命令已取消'
                       WHERE id=?""",
                    (_now(), active_start["session_id"]),
                )
            db.execute(
                """UPDATE realtime_clients
                   SET status='idle', current_session_id=NULL, message='开始命令已取消', updated_at=?
                   WHERE client_id=?""",
                (_now(), client_id),
            )
            db.commit()
            return _command_response(None, active_start["session_id"], "cancelled_start", client_id)

        session = _active_session_for_client(db, client_id)
        if not session:
            db.commit()
            return _command_response(None, None, "no_active_session", client_id)

        command = _active_command_for_client(db, client_id, "stop_capture")
        if command:
            db.commit()
            return _command_response(command["id"], command["session_id"], command["status"], client_id)

        command_id = _insert_realtime_command(
            db,
            client_id=client_id,
            session_id=session["id"],
            command_type="stop_capture",
            payload={},
        )
        db.execute(
            """UPDATE realtime_clients
               SET message='等待采集端执行停止命令', updated_at=?
               WHERE client_id=?""",
            (_now(), client_id),
        )
        db.commit()
        return _command_response(command_id, session["id"], "pending", client_id)


def get_next_realtime_command(client_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = _active_command_for_client(db, client_id)
        if not row:
            return None
        command = dict(row)
        try:
            command["payload"] = json.loads(command.get("payload") or "{}")
        except json.JSONDecodeError:
            command["payload"] = {}
        return command


def get_realtime_command(command_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM realtime_commands WHERE id=?", (command_id,)).fetchone()
        if not row:
            return None
        command = dict(row)
        try:
            command["payload"] = json.loads(command.get("payload") or "{}")
        except json.JSONDecodeError:
            command["payload"] = {}
        return command


def update_realtime_command_status(command_id, client_id, status, error_message=None):
    if status not in ("acked", "running", "completed", "failed", "cancelled"):
        raise ValueError(f"unsupported command status: {status}")

    with get_conn() as db:
        db.row_factory = sqlite3.Row
        command = db.execute(
            "SELECT * FROM realtime_commands WHERE id=? AND client_id=?",
            (command_id, client_id),
        ).fetchone()
        if not command:
            return None

        now = _now()
        timestamp_field = {
            "acked": "acked_at",
            "running": "running_at",
            "completed": "completed_at",
            "failed": "completed_at",
            "cancelled": "completed_at",
        }[status]
        db.execute(
            f"""UPDATE realtime_commands
                SET status=?, {timestamp_field}=COALESCE({timestamp_field}, ?), error_message=?
                WHERE id=? AND client_id=?""",
            (status, now, error_message, command_id, client_id),
        )

        if command["command_type"] == "start_capture" and status in ("running", "completed"):
            db.execute(
                """UPDATE realtime_clients
                   SET status='capturing', current_session_id=?, message='正在采集实时分片', updated_at=?
                   WHERE client_id=?""",
                (command["session_id"], now, client_id),
            )
        elif command["command_type"] == "stop_capture" and status == "completed":
            db.execute(
                """UPDATE realtime_sessions
                   SET status='stopped', stopped_at=?, health_status='stopped',
                       health_message='实时监测已停止'
                   WHERE id=?""",
                (now, command["session_id"]),
            )
            db.execute(
                """UPDATE realtime_clients
                   SET status='idle', current_session_id=NULL, message='采集已停止', updated_at=?
                   WHERE client_id=?""",
                (now, client_id),
            )
        elif status == "failed":
            db.execute(
                """UPDATE realtime_clients
                   SET status='error', message=?, updated_at=?
                   WHERE client_id=?""",
                (error_message or "命令执行失败", now, client_id),
            )

        db.commit()

    return get_realtime_command(command_id)


def delete_stopped_realtime_session(session_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        session = db.execute(
            "SELECT * FROM realtime_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if not session:
            return None
        if session["status"] != "stopped":
            raise RealtimeSessionNotStoppedError("Realtime session must be stopped before deletion")

        session_dict = dict(session)
        db.execute("DELETE FROM realtime_segments WHERE session_id=?", (session_id,))
        db.execute("DELETE FROM realtime_commands WHERE session_id=?", (session_id,))
        db.execute(
            """UPDATE realtime_clients
               SET current_session_id=NULL, updated_at=?
               WHERE current_session_id=?""",
            (_now(), session_id),
        )
        db.execute("DELETE FROM realtime_sessions WHERE id=?", (session_id,))
        db.commit()
        return session_dict
