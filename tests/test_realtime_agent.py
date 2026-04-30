import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows-acquisition"))

from realtime_uploader import RealtimeQueue


class FakeUploader:
    def __init__(self, queue, commands=None):
        self.queue = queue
        self.commands = list(commands or [])
        self.command_updates = []
        self.heartbeats = []
        self.uploaded_sequences = []

    def send_agent_heartbeat(self, **payload):
        self.heartbeats.append(payload)

    def poll_agent_command(self, client_id):
        if self.commands:
            return self.commands.pop(0)
        return None

    def update_agent_command_status(self, client_id, command_id, action, error_message=None):
        self.command_updates.append((client_id, command_id, action, error_message))

    def upload_item(self, item):
        self.uploaded_sequences.append(item.metadata["sequence"])
        self.queue.update_state(item, "uploaded")
        return True


class RealtimeAgentTests(unittest.TestCase):
    def test_start_command_captures_one_chunk_and_completes_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            uploader = FakeUploader(queue, commands=[{
                "id": 5,
                "session_id": 12,
                "command_type": "start_capture",
                "payload": {"chunk_duration": 2.0},
            }])
            captures = []

            def capture_chunk(duration):
                captures.append(duration)
                return b"wav-bytes"

            from realtime_agent import RealtimeAgent
            agent = RealtimeAgent(
                client_id="client-1",
                name="pond-a",
                queue=queue,
                uploader=uploader,
                capture_chunk=capture_chunk,
                sample_rate=22050,
                chunk_duration=2.0,
                now_func=lambda: "2026-04-30 10:00:00",
            )

            agent.run_once()

            self.assertEqual(captures, [2.0])
            self.assertEqual(queue.max_sequence(12), 1)
            self.assertEqual(agent.status, "capturing")
            self.assertEqual(agent.current_session_id, 12)
            self.assertEqual(
                [entry[2] for entry in uploader.command_updates],
                ["ack", "running", "complete"],
            )

    def test_start_command_uses_queue_namespace_for_fresh_session_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            stale_item = queue.enqueue(
                12,
                "client-1",
                8,
                "2026-04-30 09:59:00",
                22050,
                2.0,
                b"old-session-bytes",
            )
            queue.update_state(stale_item, "uploaded")
            uploader = FakeUploader(queue, commands=[{
                "id": 7,
                "session_id": 12,
                "command_type": "start_capture",
                "payload": {"chunk_duration": 2.0, "queue_key": "fresh-run"},
            }])

            def capture_chunk(duration):
                return b"new-session-bytes"

            from realtime_agent import RealtimeAgent
            agent = RealtimeAgent(
                client_id="client-1",
                name="pond-a",
                queue=queue,
                uploader=uploader,
                capture_chunk=capture_chunk,
                sample_rate=22050,
                chunk_duration=2.0,
                now_func=lambda: "2026-04-30 10:00:00",
            )

            agent.run_once()

            self.assertEqual(uploader.uploaded_sequences, [1])

    def test_stop_command_stops_capture_and_still_uploads_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = RealtimeQueue(Path(tmp))
            queue.enqueue(12, "client-1", 1, "2026-04-30 10:00:00", 22050, 2.0, b"old")
            uploader = FakeUploader(queue, commands=[{
                "id": 6,
                "session_id": 12,
                "command_type": "stop_capture",
                "payload": {},
            }])
            captures = []

            def capture_chunk(duration):
                captures.append(duration)
                return b"new"

            from realtime_agent import RealtimeAgent
            agent = RealtimeAgent(
                client_id="client-1",
                name="pond-a",
                queue=queue,
                uploader=uploader,
                capture_chunk=capture_chunk,
                sample_rate=22050,
                chunk_duration=2.0,
                now_func=lambda: "2026-04-30 10:00:02",
            )
            agent.status = "capturing"
            agent.current_session_id = 12
            agent.next_sequence = 2

            agent.run_once()

            self.assertEqual(captures, [])
            self.assertEqual(agent.status, "idle")
            self.assertIsNone(agent.current_session_id)
            self.assertEqual(uploader.uploaded_sequences, [1])
            self.assertEqual(
                [entry[2] for entry in uploader.command_updates],
                ["ack", "running", "complete"],
            )


if __name__ == "__main__":
    unittest.main()
