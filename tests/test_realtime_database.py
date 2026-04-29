import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
