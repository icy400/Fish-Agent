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

    def test_uploading_items_are_retried_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            queue.update_state(item, "uploading")
            restarted = RealtimeQueue(Path(tmp))
            pending = restarted.pending_items()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].metadata["state"], "uploading")

    def test_max_sequence_reads_existing_session_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            queue.enqueue(1, "client-1", 2, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            queue.enqueue(1, "client-1", 5, "2026-04-29 10:00:10", 22050, 2.0, b"def")
            queue.enqueue(2, "client-1", 99, "2026-04-29 10:00:10", 22050, 2.0, b"other")
            self.assertEqual(queue.max_sequence(1), 5)

    def test_max_sequence_can_be_scoped_to_queue_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            queue.enqueue(1, "client-1", 8, "2026-04-29 10:00:00", 22050, 2.0, b"old")
            queue.enqueue(
                1,
                "client-1",
                2,
                "2026-04-29 10:00:02",
                22050,
                2.0,
                b"fresh",
                queue_key="fresh-run",
            )

            self.assertEqual(queue.max_sequence(1, queue_key="fresh-run"), 2)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
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

    def test_plain_http_exception_marks_item_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            http = FakeHttp([Exception("network down")])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            self.assertFalse(client.upload_item(item))
            metadata = json.loads(item.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["state"], "failed_retryable")

    def test_mismatched_ack_marks_item_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            http = FakeHttp([
                FakeResponse(200, {"ack": True, "session_id": 1, "sequence": 2, "sha256": item.metadata["sha256"]})
            ])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            self.assertFalse(client.upload_item(item))
            metadata = json.loads(item.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["state"], "failed_retryable")

    def test_non_200_ack_marks_item_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 1, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            http = FakeHttp([
                FakeResponse(202, {"ack": True, "session_id": 1, "sequence": 1, "sha256": item.metadata["sha256"]})
            ])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            self.assertFalse(client.upload_item(item))
            metadata = json.loads(item.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["state"], "failed_conflict")

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

    def test_heartbeat_counts_only_requested_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 7, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            queue.update_state(item, "failed_retryable")
            queue.enqueue(2, "client-1", 99, "2026-04-29 10:00:00", 22050, 2.0, b"other")
            http = FakeHttp([FakeResponse(200, {"ack": True})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            client.send_heartbeat(1, "client-1")
            payload = http.posts[0][1]["json"]
            self.assertEqual(payload["last_sequence"], 7)
            self.assertEqual(payload["pending_chunks"], 0)
            self.assertEqual(payload["failed_retryable_chunks"], 1)

    def test_heartbeat_counts_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(1, "client-1", 7, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            queue.update_state(item, "failed_conflict")
            http = FakeHttp([FakeResponse(200, {"ack": True})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)
            client.send_heartbeat(1, "client-1")
            payload = http.posts[0][1]["json"]
            self.assertEqual(payload["failed_conflict_chunks"], 1)
            self.assertEqual(payload["client_status"], "uploading_backlog")
            self.assertEqual(payload["message"], "正在补传历史分片")

    def test_agent_heartbeat_posts_client_status_and_queue_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            item = queue.enqueue(12, "client-1", 3, "2026-04-29 10:00:00", 22050, 2.0, b"abc")
            queue.update_state(item, "failed_retryable")
            http = FakeHttp([FakeResponse(200, {"ack": True})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)

            response = client.send_agent_heartbeat(
                client_id="client-1",
                name="pond-a",
                status="capturing",
                current_session_id=12,
                sample_rate=22050,
                chunk_duration=2.0,
                message="capturing",
            )

            self.assertEqual(response.status_code, 200)
            url, kwargs = http.posts[0]
            self.assertEqual(url, "http://server:8081/api/realtime/agents/client-1/heartbeat")
            self.assertEqual(kwargs["json"]["current_session_id"], 12)
            self.assertEqual(kwargs["json"]["last_sequence"], 3)
            self.assertEqual(kwargs["json"]["failed_retryable_chunks"], 1)

    def test_agent_heartbeat_counts_only_queue_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            stale = queue.enqueue(12, "client-1", 8, "2026-04-29 10:00:00", 22050, 2.0, b"old")
            queue.update_state(stale, "failed_retryable")
            fresh = queue.enqueue(
                12,
                "client-1",
                1,
                "2026-04-29 10:00:02",
                22050,
                2.0,
                b"fresh",
                queue_key="fresh-run",
            )
            queue.update_state(fresh, "pending")
            http = FakeHttp([FakeResponse(200, {"ack": True})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)

            client.send_agent_heartbeat(
                client_id="client-1",
                status="capturing",
                current_session_id=12,
                queue_key="fresh-run",
            )

            payload = http.posts[0][1]["json"]
            self.assertEqual(payload["last_sequence"], 1)
            self.assertEqual(payload["pending_chunks"], 1)
            self.assertEqual(payload["failed_retryable_chunks"], 0)

    def test_poll_agent_command_returns_command_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            http = FakeHttp([FakeResponse(200, {"command": {"id": 5, "command_type": "start_capture"}})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)

            command = client.poll_agent_command("client-1")

            self.assertEqual(command["id"], 5)
            self.assertEqual(http.gets[0][0], "http://server:8081/api/realtime/agents/client-1/command")

    def test_update_agent_command_status_posts_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            http = FakeHttp([FakeResponse(200, {"ack": True, "command": {"status": "completed"}})])
            from realtime_uploader import RealtimeUploadClient
            client = RealtimeUploadClient("http://server:8081", queue, http=http)

            response = client.update_agent_command_status("client-1", 5, "complete")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(http.posts[0][0], "http://server:8081/api/realtime/agents/client-1/commands/5/complete")


class CreateSessionTests(unittest.TestCase):
    def test_create_session_posts_expected_payload(self):
        http = FakeHttp([FakeResponse(200, {"id": 12, "status": "running"})])
        from realtime_uploader import create_session
        session = create_session("http://server:8081/", "client-1", "pond-a", 2.0, http=http)

        self.assertEqual(session["id"], 12)
        url, kwargs = http.posts[0]
        self.assertEqual(url, "http://server:8081/api/realtime/sessions")
        self.assertEqual(kwargs["json"]["client_id"], "client-1")
        self.assertEqual(kwargs["json"]["name"], "pond-a")
        self.assertEqual(kwargs["json"]["chunk_duration"], 2.0)

    def test_create_session_raises_for_http_error(self):
        http = FakeHttp([FakeResponse(500, {"error": "server down"})])
        from realtime_uploader import create_session

        with self.assertRaises(RuntimeError):
            create_session("http://server:8081", "client-1", "pond-a", 2.0, http=http)


if __name__ == "__main__":
    unittest.main()
