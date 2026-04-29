import tempfile
import unittest
from pathlib import Path

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
