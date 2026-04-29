import json
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


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class RealtimeUploadClientTests(unittest.TestCase):
    def test_successful_upload_marks_item_uploaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            http = FakeHttp([
                FakeResponse(200, {"ack": True, "session_id": 1, "sequence": 1, "sha256": item.metadata["sha256"]})
            ])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            self.assertTrue(client.upload_item(item))
            updated = queue.pending_items()
            self.assertEqual(updated, [])

    def test_conflict_marks_item_failed_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            http = FakeHttp([FakeResponse(409, {"ack": False, "error": "sequence_conflict"})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            self.assertFalse(client.upload_item(item))
            metadata = json.loads(item.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["state"], "failed_conflict")

    def test_server_error_marks_item_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            http = FakeHttp([FakeResponse(503, {"error": "busy"})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            self.assertFalse(client.upload_item(item))
            metadata = json.loads(item.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["state"], "failed_retryable")

    def test_heartbeat_sends_queue_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 7, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            queue.update_state(item, "failed_retryable")
            http = FakeHttp([FakeResponse(200, {"ack": True})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            response = client.send_heartbeat(1, "client-1")
            self.assertEqual(response.status_code, 200)
            url, kwargs = http.posts[0]
            self.assertTrue(url.endswith("/api/realtime/sessions/1/heartbeat"))
            self.assertEqual(kwargs["json"]["last_sequence"], 7)
            self.assertEqual(kwargs["json"]["failed_retryable_chunks"], 1)


if __name__ == "__main__":
    unittest.main()
