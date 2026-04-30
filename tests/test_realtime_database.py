import tempfile
import unittest
import sqlite3
from pathlib import Path
from sqlite3 import IntegrityError

from server import database


class RealtimeDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.init_db(str(Path(self.tmp.name) / "data.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_realtime_session(self):
        session_id = database.create_realtime_session(
            client_id="pond-a-windows-01",
            name="pond-a",
            chunk_duration=2.0,
        )
        session = database.get_realtime_session(session_id)
        self.assertEqual(session["client_id"], "pond-a-windows-01")
        self.assertEqual(session["name"], "pond-a")
        self.assertEqual(session["status"], "running")

    def test_insert_segment_is_idempotent_for_same_hash(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        first = database.insert_realtime_segment(
            session_id=session_id,
            client_id="client-1",
            sequence=1,
            captured_at="2026-04-29 10:00:00",
            duration=2.0,
            sample_rate=100000,
            storage_name="1.wav",
            sha256="abc",
        )
        duplicate = database.insert_realtime_segment(
            session_id=session_id,
            client_id="client-1",
            sequence=1,
            captured_at="2026-04-29 10:00:00",
            duration=2.0,
            sample_rate=100000,
            storage_name="1.wav",
            sha256="abc",
        )
        self.assertEqual(first["duplicate"], False)
        self.assertEqual(duplicate["duplicate"], True)
        self.assertEqual(first["id"], duplicate["id"])

    def test_insert_segment_rejects_same_sequence_different_hash(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        database.insert_realtime_segment(
            session_id, "client-1", 1, "2026-04-29 10:00:00", 2.0, 100000, "1.wav", "abc"
        )
        with self.assertRaises(database.SequenceConflictError):
            database.insert_realtime_segment(
                session_id, "client-1", 1, "2026-04-29 10:00:02", 2.0, 100000, "1b.wav", "def"
            )

    def test_insert_segment_handles_integrity_error_duplicate_race(self):
        original_get_conn = database.get_conn
        existing = {"id": 42, "sha256": "abc", "session_id": 1, "sequence": 1}

        class Cursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class RaceConnection:
            row_factory = None

            def __init__(self):
                self.select_count = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=()):
                if "SELECT * FROM realtime_segments" in sql:
                    self.select_count += 1
                    return Cursor(None if self.select_count == 1 else existing)
                if "INSERT INTO realtime_segments" in sql:
                    raise IntegrityError("UNIQUE constraint failed")
                raise AssertionError(f"unexpected sql: {sql}")

        database.get_conn = RaceConnection
        try:
            result = database.insert_realtime_segment(
                session_id=1,
                client_id="client-1",
                sequence=1,
                captured_at="2026-04-29 10:00:00",
                duration=2.0,
                sample_rate=100000,
                storage_name="1.wav",
                sha256="abc",
            )
        finally:
            database.get_conn = original_get_conn

        self.assertEqual(result["duplicate"], True)
        self.assertEqual(result["id"], 42)

    def test_last_chunk_at_does_not_move_backward_for_out_of_order_segments(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        database.insert_realtime_segment(
            session_id, "client-1", 3, "2026-04-29 10:00:06", 2.0, 100000, "3.wav", "abc"
        )
        database.insert_realtime_segment(
            session_id, "client-1", 2, "2026-04-29 10:00:04", 2.0, 100000, "2.wav", "def"
        )

        session = database.get_realtime_session(session_id)
        self.assertEqual(session["last_chunk_at"], "2026-04-29 10:00:06")

    def test_latest_segments_are_ordered(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        for sequence in [1, 3, 2]:
            database.insert_realtime_segment(
                session_id, "client-1", sequence, f"2026-04-29 10:00:0{sequence}", 2.0, 100000, f"{sequence}.wav", str(sequence)
            )
        rows = database.list_realtime_segments(session_id, limit=20)
        self.assertEqual([row["sequence"] for row in rows], [1, 2, 3])

    def test_update_segment_analysis_updates_session_summary(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        inserted = database.insert_realtime_segment(
            session_id, "client-1", 1, "2026-04-29 10:00:00", 2.0, 100000, "1.wav", "abc"
        )
        database.update_realtime_segment_analysis(
            segment_id=inserted["id"],
            predicted_class="fish",
            confidence=0.91,
            fish_probability=0.91,
            background_probability=0.09,
            density_60s=0.1,
            completeness_60s=0.9,
            feeding={"level": "medium", "amount_kg": 0.5, "message": "进食正常，建议标准投喂", "confidence": "normal"},
        )
        segment = database.get_realtime_segment(inserted["id"])
        session = database.get_realtime_session(session_id)
        self.assertEqual(segment["status"], "analyzed")
        self.assertEqual(segment["predicted_class"], "fish")
        self.assertEqual(session["density_60s"], 0.1)
        self.assertEqual(session["feeding_level"], "medium")

    def test_update_segment_analysis_returns_false_for_missing_segment(self):
        result = database.update_realtime_segment_analysis(
            segment_id=999,
            predicted_class="fish",
            confidence=0.91,
            fish_probability=0.91,
            background_probability=0.09,
            density_60s=0.1,
            completeness_60s=0.9,
            feeding={"level": "medium", "amount_kg": 0.5, "message": "进食正常，建议标准投喂", "confidence": "normal"},
        )
        self.assertEqual(result, False)

    def test_update_realtime_heartbeat_updates_client_queue_counts(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        database.update_realtime_heartbeat(
            session_id=session_id,
            client_id="client-1",
            last_sequence=12,
            pending_chunks=4,
            failed_retryable_chunks=2,
            failed_conflict_chunks=1,
            client_status="uploading_backlog",
            message="正在补传历史分片",
        )
        session = database.get_realtime_session(session_id)
        self.assertEqual(session["client_last_sequence"], 12)
        self.assertEqual(session["client_pending_chunks"], 4)
        self.assertEqual(session["client_failed_retryable_chunks"], 2)
        self.assertEqual(session["client_failed_conflict_chunks"], 1)
        self.assertEqual(session["client_status"], "uploading_backlog")

    def test_init_db_migrates_legacy_realtime_sessions_client_last_sequence(self):
        db_path = str(Path(self.tmp.name) / "legacy.db")
        with sqlite3.connect(db_path) as db:
            db.execute("""
                CREATE TABLE realtime_sessions (
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
            db.execute(
                """INSERT INTO realtime_sessions
                   (client_id, name, status, chunk_duration, created_at, started_at)
                   VALUES ('client-1', 'pond-a', 'running', 2.0, '2026-04-29 10:00:00', '2026-04-29 10:00:00')"""
            )
            db.commit()

        database.init_db(db_path)
        result = database.update_realtime_heartbeat(
            session_id=1,
            client_id="client-1",
            last_sequence=12,
            pending_chunks=4,
            failed_retryable_chunks=2,
            failed_conflict_chunks=1,
            client_status="uploading_backlog",
            message="正在补传历史分片",
        )

        session = database.get_realtime_session(1)
        self.assertEqual(result, True)
        self.assertEqual(session["client_last_sequence"], 12)

    def test_update_realtime_heartbeat_returns_true_for_matching_session_and_client(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        result = database.update_realtime_heartbeat(
            session_id=session_id,
            client_id="client-1",
            last_sequence=12,
            pending_chunks=4,
            failed_retryable_chunks=2,
            failed_conflict_chunks=1,
            client_status="uploading_backlog",
            message="正在补传历史分片",
        )
        self.assertEqual(result, True)

    def test_update_realtime_heartbeat_returns_false_for_mismatched_client(self):
        session_id = database.create_realtime_session("client-1", "pond-a", 2.0)
        result = database.update_realtime_heartbeat(
            session_id=session_id,
            client_id="client-2",
            last_sequence=12,
            pending_chunks=4,
            failed_retryable_chunks=2,
            failed_conflict_chunks=1,
            client_status="uploading_backlog",
            message="正在补传历史分片",
        )
        self.assertEqual(result, False)

    def test_update_realtime_heartbeat_returns_false_for_missing_session(self):
        result = database.update_realtime_heartbeat(
            session_id=999,
            client_id="client-1",
            last_sequence=12,
            pending_chunks=4,
            failed_retryable_chunks=2,
            failed_conflict_chunks=1,
            client_status="uploading_backlog",
            message="正在补传历史分片",
        )
        self.assertEqual(result, False)

    def test_upsert_realtime_client_creates_and_updates_client(self):
        database.upsert_realtime_client(
            client_id="client-1",
            name="pond-a",
            status="idle",
            current_session_id=None,
            agent_version="agent-test",
            sample_rate=22050,
            chunk_duration=2.0,
            last_sequence=0,
            pending_chunks=0,
            failed_retryable_chunks=0,
            failed_conflict_chunks=0,
            message="ready",
        )
        database.upsert_realtime_client(
            client_id="client-1",
            name="pond-a",
            status="capturing",
            current_session_id=7,
            agent_version="agent-test",
            sample_rate=22050,
            chunk_duration=2.0,
            last_sequence=3,
            pending_chunks=2,
            failed_retryable_chunks=1,
            failed_conflict_chunks=0,
            message="capturing",
        )

        client = database.get_realtime_client("client-1")
        self.assertEqual(client["client_id"], "client-1")
        self.assertEqual(client["status"], "capturing")
        self.assertEqual(client["current_session_id"], 7)
        self.assertEqual(client["pending_chunks"], 2)
        self.assertEqual(client["failed_retryable_chunks"], 1)
        self.assertEqual(client["message"], "capturing")

    def test_list_realtime_clients_includes_online_state(self):
        database.upsert_realtime_client(
            client_id="client-1",
            name="pond-a",
            status="idle",
            current_session_id=None,
            agent_version="agent-test",
            sample_rate=22050,
            chunk_duration=2.0,
            last_sequence=0,
            pending_chunks=0,
            failed_retryable_chunks=0,
            failed_conflict_chunks=0,
            message="ready",
        )

        clients = database.list_realtime_clients(online_seconds=60)
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["client_id"], "client-1")
        self.assertEqual(clients[0]["online"], True)

    def test_enqueue_start_capture_command_creates_session_and_is_idempotent(self):
        first = database.enqueue_start_capture_command(
            client_id="client-1",
            session_name="pond-a",
            chunk_duration=2.0,
        )
        second = database.enqueue_start_capture_command(
            client_id="client-1",
            session_name="pond-a",
            chunk_duration=2.0,
        )

        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["command_id"], second["command_id"])
        self.assertEqual(first["command_status"], "pending")
        session = database.get_realtime_session(first["session_id"])
        client = database.get_realtime_client("client-1")
        self.assertEqual(session["client_id"], "client-1")
        self.assertEqual(client["current_session_id"], first["session_id"])

    def test_enqueue_stop_capture_command_is_idempotent_for_active_session(self):
        start = database.enqueue_start_capture_command("client-1", "pond-a", 2.0)
        database.update_realtime_command_status(
            command_id=start["command_id"],
            client_id="client-1",
            status="completed",
        )

        first = database.enqueue_stop_capture_command("client-1")
        second = database.enqueue_stop_capture_command("client-1")

        self.assertEqual(first["session_id"], start["session_id"])
        self.assertEqual(first["command_id"], second["command_id"])
        self.assertEqual(first["command_status"], "pending")

    def test_enqueue_stop_without_active_session_returns_noop(self):
        database.upsert_realtime_client(
            client_id="client-1",
            name="pond-a",
            status="idle",
            current_session_id=None,
            agent_version="agent-test",
            sample_rate=22050,
            chunk_duration=2.0,
            last_sequence=0,
            pending_chunks=0,
            failed_retryable_chunks=0,
            failed_conflict_chunks=0,
            message="ready",
        )

        result = database.enqueue_stop_capture_command("client-1")

        self.assertIsNone(result["session_id"])
        self.assertIsNone(result["command_id"])
        self.assertEqual(result["command_status"], "no_active_session")

    def test_agent_command_polling_and_status_transitions(self):
        start = database.enqueue_start_capture_command("client-1", "pond-a", 2.0)

        command = database.get_next_realtime_command("client-1")
        self.assertEqual(command["id"], start["command_id"])
        self.assertEqual(command["command_type"], "start_capture")
        self.assertEqual(command["status"], "pending")

        acked = database.update_realtime_command_status(
            command_id=start["command_id"],
            client_id="client-1",
            status="acked",
        )
        running = database.update_realtime_command_status(
            command_id=start["command_id"],
            client_id="client-1",
            status="running",
        )
        completed = database.update_realtime_command_status(
            command_id=start["command_id"],
            client_id="client-1",
            status="completed",
        )

        self.assertEqual(acked["status"], "acked")
        self.assertEqual(running["status"], "running")
        self.assertEqual(completed["status"], "completed")
        client = database.get_realtime_client("client-1")
        self.assertEqual(client["status"], "capturing")
        self.assertEqual(client["current_session_id"], start["session_id"])

    def test_completing_stop_command_stops_session_and_clears_client(self):
        start = database.enqueue_start_capture_command("client-1", "pond-a", 2.0)
        database.update_realtime_command_status(start["command_id"], "client-1", "completed")
        stop = database.enqueue_stop_capture_command("client-1")

        completed = database.update_realtime_command_status(
            command_id=stop["command_id"],
            client_id="client-1",
            status="completed",
        )

        session = database.get_realtime_session(start["session_id"])
        client = database.get_realtime_client("client-1")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(session["status"], "stopped")
        self.assertEqual(client["status"], "idle")
        self.assertIsNone(client["current_session_id"])


if __name__ == "__main__":
    unittest.main()
