import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows-acquisition"))

from realtime_uploader import RealtimeQueue


class RealtimeUploaderTests(unittest.TestCase):
    def test_enqueue_writes_wav_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(
                session_id=1,
                client_id="client-1",
                sequence=1,
                captured_at="2026-04-29 10:00:00",
                sample_rate=22050,
                duration=2.0,
                wav_bytes=b"abc",
            )
            self.assertTrue(item.wav_path.exists())
            self.assertTrue(item.meta_path.exists())
            self.assertEqual(item.metadata["state"], "pending")
            self.assertEqual(item.metadata["sequence"], 1)

    def test_pending_items_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            restarted = RealtimeQueue(Path(tmp))
            pending = restarted.pending_items()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].metadata["sequence"], 1)


if __name__ == "__main__":
    unittest.main()
