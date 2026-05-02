import hashlib
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"


def write_silent_wav(path):
    with wave.open(str(path), "wb") as wf:
        wf.setparams((1, 2, 22050, 44100, "NONE", "not compressed"))
        wf.writeframes(b"\x00\x00" * 44100)


class RealtimeApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "data.db")
        self.realtime_dir = Path(self.tmp.name) / "realtime_uploads"
        os.environ["FISH_AGENT_DB_PATH"] = self.db_path
        os.environ["FISH_AGENT_REALTIME_DIR"] = str(self.realtime_dir)
        self.addCleanup(lambda: os.environ.pop("FISH_AGENT_DB_PATH", None))
        self.addCleanup(lambda: os.environ.pop("FISH_AGENT_REALTIME_DIR", None))
        sys.path.insert(0, str(SERVER_DIR))
        self.addCleanup(lambda: sys.path.remove(str(SERVER_DIR)) if str(SERVER_DIR) in sys.path else None)

        import database
        database.init_db(self.db_path)

        if "app" in sys.modules:
            del sys.modules["app"]
        sys.modules["audio_infer"] = types.SimpleNamespace(classify_file=lambda path: {"segments": []})
        self.addCleanup(lambda: sys.modules.pop("audio_infer", None))
        self.app_module = importlib.import_module("app")
        self.app_module.database.init_db(self.db_path)
        self.client = TestClient(self.app_module.app)

    def _create_session(self):
        return self.client.post(
            "/api/realtime/sessions",
            json={"client_id": "client-1", "name": "pond-a"},
        ).json()

    def _chunk_metadata(self, session_id, content, sequence=1):
        return {
            "client_id": "client-1",
            "session_id": session_id,
            "sequence": sequence,
            "captured_at": "2026-04-29 10:00:00",
            "duration": 2.0,
            "sample_rate": 22050,
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def test_create_session(self):
        res = self.client.post("/api/realtime/sessions", json={
            "client_id": "client-1",
            "name": "pond-a",
            "chunk_duration": 2.0,
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["client_id"], "client-1")

    def test_upload_chunk_returns_ack_and_segment(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)

        fake_result = {
            "segments": [{
                "predicted_class": "fish",
                "confidence": 0.9,
                "probabilities": {"background": 0.1, "fish": 0.9},
            }]
        }
        with mock.patch.object(self.app_module, "classify_file", return_value=fake_result):
            res = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["ack"], True)
        self.assertEqual(data["sequence"], 1)
        self.assertEqual(data["sha256"], metadata["sha256"])
        self.assertEqual(data["segment"]["predicted_class"], "fish")
        self.assertEqual(data["segment"]["fish_probability"], 0.9)
        self.assertEqual(data["segment"]["feeding"]["level"], "minimal")
        self.assertEqual(data["segment"]["feeding"]["confidence"], "insufficient")

    def test_duplicate_chunk_same_hash_returns_duplicate_ack(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)

        with mock.patch.object(self.app_module, "classify_file", return_value={"segments": []}) as fake_infer:
            first = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )
            second = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["duplicate"], True)
        self.assertIn("feeding", second.json()["segment"])
        self.assertEqual(fake_infer.call_count, 1)
        self.assertEqual(len(list((self.realtime_dir / str(session["id"])).glob("*.wav"))), 1)

    def test_duplicate_chunk_restores_missing_audio_file(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)

        with mock.patch.object(self.app_module, "classify_file", return_value={"segments": []}):
            first = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )

        self.assertEqual(first.status_code, 200)
        import database
        row = database.list_realtime_segments(session["id"], limit=1)[0]
        stored_path = self.realtime_dir / row["storage_name"]
        stored_path.unlink()

        with mock.patch.object(self.app_module, "classify_file", return_value={"segments": []}) as fake_infer:
            duplicate = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )

        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["duplicate"], True)
        self.assertEqual(fake_infer.call_count, 0)
        self.assertEqual(stored_path.read_bytes(), content)

    def test_duplicate_chunk_different_hash_returns_conflict(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        changed_content = content + b"changed"
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)
        changed_metadata = self._chunk_metadata(session["id"], changed_content)

        with mock.patch.object(self.app_module, "classify_file", return_value={"segments": []}):
            first = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )
            conflict = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(changed_metadata)},
                files={"file": ("chunk.wav", changed_content, "audio/wav")},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["ack"], False)
        self.assertEqual(conflict.json()["error"], "sequence_conflict")
        self.assertEqual(len(list((self.realtime_dir / str(session["id"])).glob("*.wav"))), 1)

    def test_chunk_metadata_requires_session_id_and_sha256(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)
        del metadata["sha256"]

        res = self.client.post(
            f"/api/realtime/sessions/{session['id']}/chunks",
            data={"metadata": json.dumps(metadata)},
            files={"file": ("chunk.wav", content, "audio/wav")},
        )

        self.assertEqual(res.status_code, 400)
        self.assertIn("sha256", res.json()["detail"])

    def test_chunk_sequence_must_be_positive_integer(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)
        metadata["sequence"] = 1.9

        res = self.client.post(
            f"/api/realtime/sessions/{session['id']}/chunks",
            data={"metadata": json.dumps(metadata)},
            files={"file": ("chunk.wav", content, "audio/wav")},
        )

        self.assertEqual(res.status_code, 400)
        self.assertIn("integer", res.json()["detail"])

    def test_chunk_sequence_must_be_greater_than_zero(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)
        metadata["sequence"] = 0

        res = self.client.post(
            f"/api/realtime/sessions/{session['id']}/chunks",
            data={"metadata": json.dumps(metadata)},
            files={"file": ("chunk.wav", content, "audio/wav")},
        )

        self.assertEqual(res.status_code, 400)
        self.assertIn(">= 1", res.json()["detail"])

    def test_heartbeat_counts_must_be_integers(self):
        session = self._create_session()
        res = self.client.post(
            f"/api/realtime/sessions/{session['id']}/heartbeat",
            json={
                "client_id": "client-1",
                "last_sequence": True,
                "pending_chunks": 0,
                "failed_retryable_chunks": 0,
                "failed_conflict_chunks": 0,
                "client_status": "ok",
                "message": "ok",
            },
        )

        self.assertEqual(res.status_code, 400)
        self.assertIn("integer", res.json()["detail"])

    def test_heartbeat_counts_must_fit_bounds(self):
        session = self._create_session()
        res = self.client.post(
            f"/api/realtime/sessions/{session['id']}/heartbeat",
            json={
                "client_id": "client-1",
                "last_sequence": 10 ** 100,
                "pending_chunks": 0,
                "failed_retryable_chunks": 0,
                "failed_conflict_chunks": 0,
                "client_status": "ok",
                "message": "ok",
            },
        )

        self.assertEqual(res.status_code, 400)
        self.assertIn("<=", res.json()["detail"])

    def test_sample_rate_must_fit_bounds(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)
        metadata["sample_rate"] = 10 ** 100

        res = self.client.post(
            f"/api/realtime/sessions/{session['id']}/chunks",
            data={"metadata": json.dumps(metadata)},
            files={"file": ("chunk.wav", content, "audio/wav")},
        )

        self.assertEqual(res.status_code, 400)
        self.assertIn("<=", res.json()["detail"])

    def test_path_session_id_must_fit_sqlite_bounds(self):
        res = self.client.get(f"/api/realtime/sessions/{10 ** 100}")

        self.assertEqual(res.status_code, 400)
        self.assertIn("<=", res.json()["detail"])

    def test_chunk_client_id_must_match_session(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)
        metadata["client_id"] = "other-client"

        res = self.client.post(
            f"/api/realtime/sessions/{session['id']}/chunks",
            data={"metadata": json.dumps(metadata)},
            files={"file": ("chunk.wav", content, "audio/wav")},
        )

        self.assertEqual(res.status_code, 400)
        self.assertIn("client_id", res.json()["detail"])

    def test_analysis_exception_returns_ack_with_error_segment(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)

        with mock.patch.object(self.app_module, "classify_file", side_effect=RuntimeError("model failed")):
            res = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["ack"], True)
        self.assertEqual(res.json()["segment"]["status"], "error")
        self.assertIn("model failed", res.json()["segment"]["error"])

    def test_old_backfill_does_not_change_latest_window_summary(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        background_result = {
            "segments": [{
                "predicted_class": "background",
                "confidence": 0.95,
                "probabilities": {"background": 0.95, "fish": 0.05},
            }]
        }
        fish_result = {
            "segments": [{
                "predicted_class": "fish",
                "confidence": 0.95,
                "probabilities": {"background": 0.05, "fish": 0.95},
            }]
        }

        with mock.patch.object(self.app_module, "classify_file", return_value=background_result):
            for sequence in range(2, 32):
                metadata = self._chunk_metadata(session["id"], content, sequence=sequence)
                res = self.client.post(
                    f"/api/realtime/sessions/{session['id']}/chunks",
                    data={"metadata": json.dumps(metadata)},
                    files={"file": ("chunk.wav", content, "audio/wav")},
                )
                self.assertEqual(res.status_code, 200)

        with mock.patch.object(self.app_module, "classify_file", return_value=fish_result):
            metadata = self._chunk_metadata(session["id"], content, sequence=1)
            backfill = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )

        summary = self.client.get(f"/api/realtime/sessions/{session['id']}")
        self.assertEqual(backfill.status_code, 200)
        self.assertEqual(summary.json()["density_60s"], 0)
        self.assertEqual(summary.json()["feeding_level"], "minimal")

    def test_summary_segments_and_heartbeat_endpoints(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)

        with mock.patch.object(self.app_module, "classify_file", return_value={
            "segments": [{
                "predicted_class": "fish",
                "confidence": 0.91,
                "probabilities": {"background": 0.09, "fish": 0.91},
            }]
        }):
            upload = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )
        heartbeat = self.client.post(
            f"/api/realtime/sessions/{session['id']}/heartbeat",
            json={
                "client_id": "client-1",
                "last_sequence": 1,
                "pending_chunks": 2,
                "failed_retryable_chunks": 1,
                "failed_conflict_chunks": 0,
                "client_status": "uploading_backlog",
                "message": "正在补传历史分片",
            },
        )
        summary = self.client.get(f"/api/realtime/sessions/{session['id']}")
        segments = self.client.get(f"/api/realtime/sessions/{session['id']}/segments")

        self.assertEqual(upload.status_code, 200)
        self.assertEqual(heartbeat.status_code, 200)
        self.assertEqual(heartbeat.json()["ack"], True)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["client_pending_chunks"], 2)
        self.assertEqual(summary.json()["feeding_level"], "minimal")
        self.assertEqual(segments.status_code, 200)
        self.assertEqual(segments.json()["segments"][0]["sequence"], 1)

    def test_upload_chunk_stores_sound_intensity_and_updates_60s_average(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        background_result = {
            "segments": [{
                "predicted_class": "background",
                "confidence": 0.95,
                "probabilities": {"background": 0.95, "fish": 0.05},
            }]
        }

        with (
            mock.patch.object(self.app_module, "classify_file", return_value=background_result),
            mock.patch.object(self.app_module, "calculate_sound_intensity", side_effect=[10.0, 20.0], create=True) as fake_energy,
        ):
            for sequence in (1, 2):
                metadata = self._chunk_metadata(session["id"], content, sequence=sequence)
                res = self.client.post(
                    f"/api/realtime/sessions/{session['id']}/chunks",
                    data={"metadata": json.dumps(metadata)},
                    files={"file": ("chunk.wav", content, "audio/wav")},
                )
                self.assertEqual(res.status_code, 200)

        summary = self.client.get(f"/api/realtime/sessions/{session['id']}")
        segments = self.client.get(f"/api/realtime/sessions/{session['id']}/segments?limit=2")

        self.assertEqual(fake_energy.call_count, 2)
        self.assertEqual(summary.json()["sound_intensity_60s"], 15.0)
        self.assertEqual([row["sound_intensity"] for row in segments.json()["segments"]], [10.0, 20.0])

    def test_stop_session_marks_session_stopped(self):
        session = self._create_session()
        res = self.client.post(f"/api/realtime/sessions/{session['id']}/stop")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "stopped")
        self.assertEqual(res.json()["health_status"], "stopped")
        self.assertEqual(res.json()["health_message"], "实时监测已停止")
        self.assertIsNotNone(res.json()["stopped_at"])

    def test_segments_endpoint_includes_missing_placeholder(self):
        session = self._create_session()
        import database
        database.insert_realtime_segment(
            session["id"], "client-1", 1, "2026-04-29 10:00:00", 2.0, 22050, "1.wav", "a"
        )
        database.insert_realtime_segment(
            session["id"], "client-1", 3, "2026-04-29 10:00:04", 2.0, 22050, "3.wav", "c"
        )

        res = self.client.get(f"/api/realtime/sessions/{session['id']}/segments?limit=3")

        self.assertEqual(res.status_code, 200)
        self.assertEqual([row["sequence"] for row in res.json()["segments"]], [1, 2, 3])
        self.assertEqual(res.json()["segments"][1]["status"], "missing")

    def test_export_current_session_json_includes_summary_and_all_segments(self):
        session = self._create_session()
        import database
        for sequence in range(1, 36):
            inserted = database.insert_realtime_segment(
                session["id"],
                "client-1",
                sequence,
                f"2026-04-29 10:00:{sequence:02d}",
                2.0,
                22050,
                f"{sequence}.wav",
                str(sequence),
            )
            database.update_realtime_segment_analysis(
                segment_id=inserted["id"],
                predicted_class="background",
                confidence=0.9,
                fish_probability=0.1,
                background_probability=0.9,
                density_60s=0.0,
                completeness_60s=1.0,
                feeding={"level": "minimal", "amount_kg": 0.1, "message": "进食较弱，建议不投喂或极少量", "confidence": "normal"},
                sound_intensity=float(sequence),
                sound_intensity_60s=20.5,
            )

        res = self.client.get(f"/api/realtime/sessions/{session['id']}/export?format=json")

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["session"]["id"], session["id"])
        self.assertIn("sound_intensity_60s", data["session"])
        self.assertEqual(len(data["segments"]), 35)
        self.assertEqual(data["segments"][0]["sequence"], 1)
        self.assertEqual(data["segments"][-1]["sequence"], 35)
        self.assertIn("sound_intensity", data["segments"][0])
        self.assertNotIn("sound_intensity_60s", data["segments"][0])
        self.assertIn("note", data["segments"][0])

    def test_export_current_session_csv_contains_summary_and_detail_sections(self):
        session = self._create_session()
        import database
        inserted = database.insert_realtime_segment(
            session["id"], "client-1", 1, "2026-04-29 10:00:00", 2.0, 22050, "1.wav", "a"
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
            sound_intensity=12.5,
            sound_intensity_60s=12.5,
        )

        res = self.client.get(f"/api/realtime/sessions/{session['id']}/export?format=csv")
        text = res.text

        self.assertEqual(res.status_code, 200)
        self.assertIn("会话信息", text)
        self.assertIn("分片分析", text)
        self.assertIn("60s平均声音能量强度", text)
        self.assertIn("平均声音能量强度", text)
        self.assertIn("建议/备注", text)
        self.assertNotIn("健康状态", text)
        self.assertNotIn("健康消息", text)

    def test_agent_heartbeat_registers_client_and_clients_endpoint_lists_it(self):
        heartbeat = self.client.post(
            "/api/realtime/agents/client-1/heartbeat",
            json={
                "name": "pond-a",
                "status": "idle",
                "current_session_id": None,
                "agent_version": "test-agent",
                "sample_rate": 22050,
                "chunk_duration": 2.0,
                "last_sequence": 0,
                "pending_chunks": 0,
                "failed_retryable_chunks": 0,
                "failed_conflict_chunks": 0,
                "message": "ready",
            },
        )
        clients = self.client.get("/api/realtime/clients")

        self.assertEqual(heartbeat.status_code, 200)
        self.assertEqual(heartbeat.json()["ack"], True)
        self.assertEqual(clients.status_code, 200)
        self.assertEqual(clients.json()["clients"][0]["client_id"], "client-1")
        self.assertEqual(clients.json()["clients"][0]["status"], "idle")
        self.assertEqual(clients.json()["clients"][0]["online"], True)

    def test_start_command_endpoint_creates_session_and_agent_can_poll_it(self):
        start = self.client.post(
            "/api/realtime/clients/client-1/commands/start",
            json={"session_name": "pond-a", "chunk_duration": 2.0},
        )
        command = self.client.get("/api/realtime/agents/client-1/command")

        self.assertEqual(start.status_code, 200)
        self.assertIsNotNone(start.json()["session_id"])
        self.assertIsNotNone(start.json()["command_id"])
        self.assertEqual(start.json()["command_status"], "pending")
        self.assertEqual(command.status_code, 200)
        self.assertEqual(command.json()["command"]["id"], start.json()["command_id"])
        self.assertEqual(command.json()["command"]["command_type"], "start_capture")
        self.assertEqual(command.json()["command"]["session_id"], start.json()["session_id"])
        self.assertIn("queue_key", command.json()["command"]["payload"])
        self.assertEqual(command.json()["command"]["payload"]["next_sequence"], 1)

    def test_command_session_rejects_chunk_from_wrong_queue_namespace(self):
        start = self.client.post(
            "/api/realtime/clients/client-1/commands/start",
            json={"session_name": "pond-a", "chunk_duration": 2.0},
        ).json()
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        metadata = self._chunk_metadata(start["session_id"], content, sequence=8)

        with mock.patch.object(self.app_module, "classify_file", return_value={"segments": []}):
            res = self.client.post(
                f"/api/realtime/sessions/{start['session_id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )

        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"], "queue_key_conflict")

    def test_start_command_is_idempotent_for_repeated_clicks(self):
        first = self.client.post(
            "/api/realtime/clients/client-1/commands/start",
            json={"session_name": "pond-a", "chunk_duration": 2.0},
        )
        second = self.client.post(
            "/api/realtime/clients/client-1/commands/start",
            json={"session_name": "pond-a", "chunk_duration": 2.0},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["session_id"], second.json()["session_id"])
        self.assertEqual(first.json()["command_id"], second.json()["command_id"])

    def test_agent_command_status_complete_start_then_stop(self):
        start = self.client.post(
            "/api/realtime/clients/client-1/commands/start",
            json={"session_name": "pond-a", "chunk_duration": 2.0},
        ).json()

        ack = self.client.post(f"/api/realtime/agents/client-1/commands/{start['command_id']}/ack")
        running = self.client.post(f"/api/realtime/agents/client-1/commands/{start['command_id']}/running")
        complete = self.client.post(f"/api/realtime/agents/client-1/commands/{start['command_id']}/complete")
        stop = self.client.post("/api/realtime/clients/client-1/commands/stop")
        stop_complete = self.client.post(
            f"/api/realtime/agents/client-1/commands/{stop.json()['command_id']}/complete"
        )
        session = self.client.get(f"/api/realtime/sessions/{start['session_id']}")
        client = self.client.get("/api/realtime/clients/client-1")

        self.assertEqual(ack.status_code, 200)
        self.assertEqual(running.status_code, 200)
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(complete.json()["command"]["status"], "completed")
        self.assertEqual(stop.status_code, 200)
        self.assertEqual(stop.json()["session_id"], start["session_id"])
        self.assertEqual(stop_complete.status_code, 200)
        self.assertEqual(session.json()["status"], "stopped")
        self.assertEqual(client.json()["client"]["status"], "idle")
        self.assertIsNone(client.json()["client"]["current_session_id"])

    def test_agent_command_fail_marks_command_failed(self):
        start = self.client.post(
            "/api/realtime/clients/client-1/commands/start",
            json={"session_name": "pond-a", "chunk_duration": 2.0},
        ).json()

        failed = self.client.post(
            f"/api/realtime/agents/client-1/commands/{start['command_id']}/fail",
            json={"error_message": "DAQ offline"},
        )
        client = self.client.get("/api/realtime/clients/client-1")

        self.assertEqual(failed.status_code, 200)
        self.assertEqual(failed.json()["command"]["status"], "failed")
        self.assertEqual(failed.json()["command"]["error_message"], "DAQ offline")
        self.assertEqual(client.json()["client"]["status"], "error")
        self.assertEqual(client.json()["client"]["message"], "DAQ offline")

    def test_client_sessions_endpoint_lists_history(self):
        first = self._create_session()
        self.client.post(f"/api/realtime/sessions/{first['id']}/stop")
        second = self.client.post(
            "/api/realtime/sessions",
            json={"client_id": "client-1", "name": "pond-a-2"},
        ).json()

        res = self.client.get("/api/realtime/clients/client-1/sessions?limit=10")

        self.assertEqual(res.status_code, 200)
        self.assertEqual([row["id"] for row in res.json()["sessions"]], [second["id"], first["id"]])
        self.assertEqual(res.json()["sessions"][0]["client_id"], "client-1")

    def test_delete_running_session_returns_conflict(self):
        session = self._create_session()

        res = self.client.delete(f"/api/realtime/sessions/{session['id']}")

        self.assertEqual(res.status_code, 409)
        self.assertIn("stopped", res.json()["detail"])
        self.assertEqual(self.client.get(f"/api/realtime/sessions/{session['id']}").status_code, 200)

    def test_delete_stopped_session_removes_database_rows_and_audio_directory(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        session = self._create_session()
        metadata = self._chunk_metadata(session["id"], content)

        with mock.patch.object(self.app_module, "classify_file", return_value={"segments": []}):
            upload = self.client.post(
                f"/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata)},
                files={"file": ("chunk.wav", content, "audio/wav")},
            )
        self.assertEqual(upload.status_code, 200)
        session_dir = self.realtime_dir / str(session["id"])
        self.assertTrue(session_dir.exists())
        self.client.post(f"/api/realtime/sessions/{session['id']}/stop")

        deleted = self.client.delete(f"/api/realtime/sessions/{session['id']}")

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted"], True)
        self.assertFalse(session_dir.exists())
        self.assertEqual(self.client.get(f"/api/realtime/sessions/{session['id']}").status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/realtime/sessions/{session['id']}/segments").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
