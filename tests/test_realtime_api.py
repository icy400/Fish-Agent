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


if __name__ == "__main__":
    unittest.main()
