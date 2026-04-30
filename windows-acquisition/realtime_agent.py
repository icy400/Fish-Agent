"""Command-driven realtime acquisition agent core.

This module is intentionally hardware-neutral: callers inject the function that
captures one WAV chunk. That keeps the control loop testable without the DAQ DLL.
"""

from datetime import datetime


class RealtimeAgent:
    def __init__(self, client_id, name, queue, uploader, capture_chunk,
                 sample_rate, chunk_duration=2.0, now_func=None):
        self.client_id = client_id
        self.name = name
        self.queue = queue
        self.uploader = uploader
        self.capture_chunk = capture_chunk
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.now_func = now_func or (lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.status = "idle"
        self.current_session_id = None
        self.next_sequence = 1
        self.message = "等待前端采集命令"

    def run_once(self):
        self.send_heartbeat()
        command = self.uploader.poll_agent_command(self.client_id)
        if command:
            self.handle_command(command)

        self.upload_pending()

        if self.status == "capturing" and self.current_session_id is not None:
            self.capture_once()
            self.upload_pending()

    def send_heartbeat(self):
        self.uploader.send_agent_heartbeat(
            client_id=self.client_id,
            name=self.name,
            status=self.status,
            current_session_id=self.current_session_id,
            sample_rate=self.sample_rate,
            chunk_duration=self.chunk_duration,
            message=self.message,
        )

    def handle_command(self, command):
        command_type = command.get("command_type")
        if command_type == "start_capture":
            self._handle_start(command)
        elif command_type == "stop_capture":
            self._handle_stop(command)

    def _handle_start(self, command):
        command_id = command["id"]
        session_id = command["session_id"]
        payload = command.get("payload") or {}
        self.uploader.update_agent_command_status(self.client_id, command_id, "ack")
        self.uploader.update_agent_command_status(self.client_id, command_id, "running")
        self.current_session_id = session_id
        self.chunk_duration = float(payload.get("chunk_duration", self.chunk_duration))
        self.next_sequence = self.queue.max_sequence(session_id) + 1
        self.status = "capturing"
        self.message = "正在采集实时分片"
        self.uploader.update_agent_command_status(self.client_id, command_id, "complete")

    def _handle_stop(self, command):
        command_id = command["id"]
        self.uploader.update_agent_command_status(self.client_id, command_id, "ack")
        self.uploader.update_agent_command_status(self.client_id, command_id, "running")
        self.status = "idle"
        self.current_session_id = None
        self.message = "采集已停止，继续补传队列"
        self.uploader.update_agent_command_status(self.client_id, command_id, "complete")

    def capture_once(self):
        wav_bytes = self.capture_chunk(self.chunk_duration)
        captured_at = self._timestamp()
        self.queue.enqueue(
            session_id=self.current_session_id,
            client_id=self.client_id,
            sequence=self.next_sequence,
            captured_at=captured_at,
            sample_rate=self.sample_rate,
            duration=self.chunk_duration,
            wav_bytes=wav_bytes,
        )
        self.next_sequence += 1

    def upload_pending(self):
        for item in self.queue.pending_items():
            self.uploader.upload_item(item)

    def _timestamp(self):
        value = self.now_func()
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value
