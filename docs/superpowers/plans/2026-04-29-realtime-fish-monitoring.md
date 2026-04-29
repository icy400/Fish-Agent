# Real-Time Fish Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reliable realtime fish acoustic monitoring mode that receives 2-second Windows acquisition chunks, computes fish-sound density, and shows the current feeding recommendation plus the latest 20 chunk results in the frontend.

**Architecture:** Add focused backend modules for density calculation, realtime persistence, and realtime API routes. Keep inference in the existing `audio_infer.py` path, add a static `realtime.html` page, and extend the Windows client with a durable upload queue and heartbeat reporting.

**Tech Stack:** Python standard library, FastAPI, SQLite, existing TensorFlow Lite inference, plain HTML/CSS/JavaScript, Windows `requests` upload client.

---

## File Structure

- Create `server/realtime_density.py`: pure functions for density windows, completeness, feeding recommendation confidence, and latest-20 placeholders.
- Modify `server/database.py`: add realtime session/segment tables and CRUD helpers.
- Modify `server/app.py`: add realtime API endpoints and mount new page links.
- Create `server/static/realtime.html`: realtime monitoring dashboard.
- Modify `server/static/index.html`, `server/static/upload.html`, `server/static/detail.html`: add realtime nav link.
- Modify `server/static/style.css`: add compact realtime status, timeline, and table styles.
- Create `windows-acquisition/realtime_uploader.py`: durable local queue, retry, heartbeat, session creation, and chunk upload client.
- Modify `windows-acquisition/main.py`: add `--realtime`, `--session-id`, `--session-name`, `--client-id`, and queue directory arguments.
- Modify `windows-acquisition/config.yaml`: add realtime defaults.
- Create `tests/test_realtime_density.py`: density and recommendation tests.
- Create `tests/test_realtime_database.py`: SQLite persistence and idempotency tests.
- Create `tests/test_realtime_api.py`: FastAPI endpoint tests with fake inference.
- Create `tests/test_realtime_uploader.py`: Windows queue/retry tests using temp dirs and fake HTTP client.
- Create `server/scripts/replay_realtime.py`: local replay tool that sends an existing WAV as realtime chunks for manual verification.

## Implementation Notes

- Do not remove or rewrite the existing upload/file-analysis workflow.
- Keep realtime storage separate from `files`, `uploads`, and `results`. Use `server/realtime_uploads/`.
- Preserve existing frontend zero-dependency style.
- Use `unittest` unless the repo adopts pytest before implementation.
- In tests that import `app.py`, inject fake inference before exercising endpoints so TensorFlow/librosa are not required for unit tests.
- Commit after each completed task if the working tree is clean enough to allow focused commits.

---

### Task 1: Density And Recommendation Core

**Files:**
- Create: `server/realtime_density.py`
- Test: `tests/test_realtime_density.py`

- [ ] **Step 1: Write the failing density tests**

Create `tests/test_realtime_density.py`:

```python
import unittest

from server.realtime_density import (
    build_latest_sequence_rows,
    calculate_density,
    feeding_from_density,
)


class RealtimeDensityTests(unittest.TestCase):
    def test_empty_window_is_insufficient(self):
        summary = calculate_density([], expected_chunks=30)
        self.assertEqual(summary["density_60s"], 0)
        self.assertEqual(summary["completeness_60s"], 0)
        self.assertEqual(summary["fish_chunks_60s"], 0)
        self.assertEqual(summary["received_chunks_60s"], 0)

        feeding = feeding_from_density(summary["density_60s"], summary["completeness_60s"])
        self.assertEqual(feeding["level"], "minimal")
        self.assertEqual(feeding["confidence"], "insufficient")
        self.assertIn("数据不足", feeding["message"])

    def test_density_counts_only_received_chunks(self):
        chunks = [
            {"sequence": 1, "predicted_class": "fish"},
            {"sequence": 2, "predicted_class": "background"},
            {"sequence": 3, "predicted_class": "fish"},
        ]
        summary = calculate_density(chunks, expected_chunks=30)
        self.assertEqual(summary["fish_chunks_60s"], 2)
        self.assertEqual(summary["received_chunks_60s"], 3)
        self.assertAlmostEqual(summary["density_60s"], 0.6667)
        self.assertAlmostEqual(summary["completeness_60s"], 0.1)

    def test_feeding_confidence_tracks_completeness(self):
        high_low_confidence = feeding_from_density(0.2, 0.7)
        self.assertEqual(high_low_confidence["level"], "high")
        self.assertEqual(high_low_confidence["confidence"], "low")

        high_normal = feeding_from_density(0.2, 0.9)
        self.assertEqual(high_normal["level"], "high")
        self.assertEqual(high_normal["amount_kg"], 0.8)
        self.assertEqual(high_normal["confidence"], "normal")

    def test_latest_rows_include_missing_placeholders(self):
        rows = build_latest_sequence_rows(
            [
                {"sequence": 3, "status": "analyzed"},
                {"sequence": 5, "status": "analyzed"},
            ],
            limit=4,
        )
        self.assertEqual([row["sequence"] for row in rows], [2, 3, 4, 5])
        self.assertEqual(rows[0]["status"], "missing")
        self.assertEqual(rows[1]["status"], "analyzed")
        self.assertEqual(rows[2]["status"], "missing")
        self.assertEqual(rows[3]["status"], "analyzed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_density
```

Expected: fail with `ModuleNotFoundError: No module named 'server.realtime_density'`.

- [ ] **Step 3: Implement the density module**

Create `server/realtime_density.py`:

```python
"""Realtime fish-sound density and feeding recommendation helpers."""


FEEDING_THRESHOLDS = [
    (0.15, 0.8, "high", "进食活跃，建议足量投喂"),
    (0.08, 0.5, "medium", "进食正常，建议标准投喂"),
    (0.03, 0.3, "low", "进食一般，建议少量投喂"),
]


def calculate_density(chunks, expected_chunks=30):
    received = [c for c in chunks if c.get("status", "analyzed") == "analyzed"]
    fish_count = sum(1 for c in received if c.get("predicted_class") == "fish")
    received_count = len(received)
    density = fish_count / received_count if received_count else 0
    completeness = received_count / expected_chunks if expected_chunks else 0
    return {
        "density_60s": round(density, 4),
        "completeness_60s": round(min(completeness, 1), 4),
        "fish_chunks_60s": fish_count,
        "received_chunks_60s": received_count,
        "expected_chunks_60s": expected_chunks,
        "missing_count_60s": max(expected_chunks - received_count, 0),
    }


def feeding_from_density(density, completeness):
    if density >= 0.15:
        amount, level, message = 0.8, "high", "进食活跃，建议足量投喂"
    elif density >= 0.08:
        amount, level, message = 0.5, "medium", "进食正常，建议标准投喂"
    elif density >= 0.03:
        amount, level, message = 0.3, "low", "进食一般，建议少量投喂"
    else:
        amount, level, message = 0.1, "minimal", "进食较弱，建议不投喂或极少量"

    if completeness >= 0.8:
        confidence = "normal"
    elif completeness >= 0.5:
        confidence = "low"
        message = f"{message}（数据完整度较低）"
    else:
        confidence = "insufficient"
        level = "minimal"
        amount = 0.1
        message = "数据不足，建议保守处理"

    return {
        "level": level,
        "amount_kg": amount,
        "message": message,
        "confidence": confidence,
    }


def build_latest_sequence_rows(segments, limit=20):
    if not segments:
        return []

    by_sequence = {int(row["sequence"]): row for row in segments}
    latest_sequence = max(by_sequence)
    first_sequence = max(1, latest_sequence - limit + 1)
    rows = []

    for sequence in range(first_sequence, latest_sequence + 1):
        existing = by_sequence.get(sequence)
        if existing:
            rows.append(existing)
        else:
            rows.append({
                "sequence": sequence,
                "status": "missing",
                "captured_at": None,
                "message": "分片缺失，等待补传",
            })

    return rows[-limit:]
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_density
```

Expected: `Ran 4 tests ... OK`.

- [ ] **Step 5: Commit**

```bash
git add server/realtime_density.py tests/test_realtime_density.py
git commit -m "Add realtime density calculations"
```

---

### Task 2: Realtime Database Persistence

**Files:**
- Modify: `server/database.py`
- Test: `tests/test_realtime_database.py`

- [ ] **Step 1: Write failing database tests**

Create `tests/test_realtime_database.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_database
```

Expected: fail because `create_realtime_session` is missing.

- [ ] **Step 3: Add tables in `init_db`**

Modify `server/database.py` inside `init_db(path)` after the existing `files` table creation:

```python
        db.execute("""
            CREATE TABLE IF NOT EXISTS realtime_sessions (
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
        db.execute("""
            CREATE TABLE IF NOT EXISTS realtime_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                client_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                duration REAL NOT NULL,
                sample_rate INTEGER,
                storage_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                predicted_class TEXT,
                confidence REAL DEFAULT 0,
                fish_probability REAL DEFAULT 0,
                background_probability REAL DEFAULT 0,
                density_60s REAL DEFAULT 0,
                completeness_60s REAL DEFAULT 0,
                feeding_level TEXT,
                feeding_amount REAL DEFAULT 0,
                feeding_message TEXT,
                feeding_confidence TEXT,
                error_message TEXT,
                UNIQUE(session_id, sequence)
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_realtime_segments_session_captured
            ON realtime_segments(session_id, captured_at)
        """)
```

- [ ] **Step 4: Add database helper functions**

Append to `server/database.py`:

```python
class SequenceConflictError(Exception):
    pass


def _row_to_dict(row):
    return dict(row) if row else None


def create_realtime_session(client_id, name=None, chunk_duration=2.0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as db:
        cur = db.execute(
            """INSERT INTO realtime_sessions
               (client_id, name, status, chunk_duration, created_at, started_at, health_status, health_message)
               VALUES (?, ?, 'running', ?, ?, ?, 'waiting', '等待实时分片')""",
            (client_id, name, chunk_duration, now, now),
        )
        db.commit()
        return cur.lastrowid


def get_realtime_session(session_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM realtime_sessions WHERE id=?", (session_id,)).fetchone()
        return _row_to_dict(row)


def insert_realtime_segment(session_id, client_id, sequence, captured_at, duration, sample_rate, storage_name, sha256):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        existing = db.execute(
            "SELECT * FROM realtime_segments WHERE session_id=? AND sequence=?",
            (session_id, sequence),
        ).fetchone()
        if existing:
            existing_dict = dict(existing)
            if existing_dict["sha256"] != sha256:
                raise SequenceConflictError("sequence already exists with different sha256")
            return {"duplicate": True, "id": existing_dict["id"], "row": existing_dict}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = db.execute(
            """INSERT INTO realtime_segments
               (session_id, client_id, sequence, captured_at, received_at, duration, sample_rate,
                storage_name, sha256, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded')""",
            (session_id, client_id, sequence, captured_at, now, duration, sample_rate, storage_name, sha256),
        )
        db.execute(
            "UPDATE realtime_sessions SET last_chunk_at=?, health_status='receiving', health_message='正在接收实时分片' WHERE id=?",
            (captured_at, session_id),
        )
        db.commit()
        return {"duplicate": False, "id": cur.lastrowid, "row": get_realtime_segment(cur.lastrowid)}


def get_realtime_segment(segment_id):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM realtime_segments WHERE id=?", (segment_id,)).fetchone()
        return _row_to_dict(row)


def list_realtime_segments(session_id, limit=20):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT * FROM realtime_segments
               WHERE session_id=?
               ORDER BY sequence DESC
               LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
```

- [ ] **Step 5: Run database tests and verify GREEN**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_database
```

Expected: `Ran 4 tests ... OK`.

- [ ] **Step 6: Commit**

```bash
git add server/database.py tests/test_realtime_database.py
git commit -m "Add realtime persistence"
```

---

### Task 3: Segment Result Updates And Session Summary

**Files:**
- Modify: `server/database.py`
- Modify: `server/realtime_density.py`
- Test: `tests/test_realtime_database.py`

- [ ] **Step 1: Extend failing tests for analyzed results and heartbeat**

Append to `tests/test_realtime_database.py`:

```python
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
        self.assertEqual(session["client_pending_chunks"], 4)
        self.assertEqual(session["client_failed_retryable_chunks"], 2)
        self.assertEqual(session["client_failed_conflict_chunks"], 1)
        self.assertEqual(session["client_status"], "uploading_backlog")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_database
```

Expected: fail because `update_realtime_segment_analysis` and `update_realtime_heartbeat` are missing.

- [ ] **Step 3: Add update helpers**

Append to `server/database.py`:

```python
def update_realtime_segment_analysis(segment_id, predicted_class, confidence, fish_probability,
                                     background_probability, density_60s, completeness_60s, feeding):
    with get_conn() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT session_id FROM realtime_segments WHERE id=?", (segment_id,)).fetchone()
        if not row:
            return False

        session_id = row["session_id"]
        db.execute(
            """UPDATE realtime_segments
               SET status='analyzed', predicted_class=?, confidence=?, fish_probability=?,
                   background_probability=?, density_60s=?, completeness_60s=?,
                   feeding_level=?, feeding_amount=?, feeding_message=?, feeding_confidence=?, error_message=NULL
               WHERE id=?""",
            (
                predicted_class,
                confidence,
                fish_probability,
                background_probability,
                density_60s,
                completeness_60s,
                feeding.get("level"),
                feeding.get("amount_kg"),
                feeding.get("message"),
                feeding.get("confidence"),
                segment_id,
            ),
        )
        db.execute(
            """UPDATE realtime_sessions
               SET density_60s=?, completeness_60s=?, feeding_level=?, feeding_amount=?,
                   feeding_message=?, feeding_confidence=?, health_status='receiving',
                   health_message='实时监测正常'
               WHERE id=?""",
            (
                density_60s,
                completeness_60s,
                feeding.get("level"),
                feeding.get("amount_kg"),
                feeding.get("message"),
                feeding.get("confidence"),
                session_id,
            ),
        )
        db.commit()
        return True


def update_realtime_segment_error(segment_id, error_message):
    with get_conn() as db:
        db.execute(
            "UPDATE realtime_segments SET status='error', error_message=? WHERE id=?",
            (error_message, segment_id),
        )
        db.commit()


def update_realtime_heartbeat(session_id, client_id, last_sequence, pending_chunks,
                              failed_retryable_chunks, failed_conflict_chunks, client_status, message):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as db:
        db.execute(
            """UPDATE realtime_sessions
               SET last_heartbeat_at=?, client_pending_chunks=?, client_failed_retryable_chunks=?,
                   client_failed_conflict_chunks=?, client_status=?, health_status=?,
                   health_message=?
               WHERE id=? AND client_id=?""",
            (
                now,
                pending_chunks,
                failed_retryable_chunks,
                failed_conflict_chunks,
                client_status,
                client_status,
                message,
                session_id,
                client_id,
            ),
        )
        db.commit()
        return db.total_changes > 0
```

- [ ] **Step 4: Run database tests and verify GREEN**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_database
```

Expected: all realtime database tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/database.py tests/test_realtime_database.py
git commit -m "Track realtime segment analysis"
```

---

### Task 4: Realtime API Endpoints

**Files:**
- Modify: `server/app.py`
- Modify: `server/database.py`
- Test: `tests/test_realtime_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_realtime_api.py`:

```python
import hashlib
import importlib
import json
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
        sys.path.insert(0, str(SERVER_DIR))

        import database
        database.init_db(str(Path(self.tmp.name) / "data.db"))

        if "app" in sys.modules:
            del sys.modules["app"]
        sys.modules["audio_infer"] = types.SimpleNamespace(classify_file=lambda path: {"segments": []})
        self.addCleanup(lambda: sys.modules.pop("audio_infer", None))
        self.app_module = importlib.import_module("app")
        self.app_module.DB_PATH = str(Path(self.tmp.name) / "data.db")
        self.app_module.REALTIME_DIR = Path(self.tmp.name) / "realtime_uploads"
        self.app_module.REALTIME_DIR.mkdir(exist_ok=True)
        self.app_module.database.init_db(self.app_module.DB_PATH)
        self.client = TestClient(self.app_module.app)

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
        sha = hashlib.sha256(content).hexdigest()
        session = self.client.post("/api/realtime/sessions", json={"client_id": "client-1", "name": "pond-a"}).json()
        metadata = {
            "client_id": "client-1",
            "session_id": session["id"],
            "sequence": 1,
            "captured_at": "2026-04-29 10:00:00",
            "duration": 2.0,
            "sample_rate": 22050,
            "sha256": sha,
        }

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
        self.assertEqual(data["segment"]["predicted_class"], "fish")

    def test_duplicate_chunk_same_hash_returns_duplicate_ack(self):
        wav_path = Path(self.tmp.name) / "chunk.wav"
        write_silent_wav(wav_path)
        content = wav_path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        session = self.client.post("/api/realtime/sessions", json={"client_id": "client-1", "name": "pond-a"}).json()
        metadata = {
            "client_id": "client-1",
            "session_id": session["id"],
            "sequence": 1,
            "captured_at": "2026-04-29 10:00:00",
            "duration": 2.0,
            "sample_rate": 22050,
            "sha256": sha,
        }
        with mock.patch.object(self.app_module, "classify_file", return_value={"segments": []}):
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_api
```

Expected: fail with 404 responses for realtime endpoints.

- [ ] **Step 3: Add realtime directory and imports**

Modify `server/app.py` near existing directory constants:

```python
REALTIME_DIR = BASE_DIR / "realtime_uploads"
REALTIME_DIR.mkdir(exist_ok=True)
```

Modify imports:

```python
from datetime import datetime

from realtime_density import build_latest_sequence_rows, calculate_density, feeding_from_density
```

- [ ] **Step 4: Add request helpers in `app.py`**

Add before API routes:

```python
def _chunk_analysis_from_result(result):
    segments = result.get("segments") or []
    if not segments:
        return {
            "predicted_class": "background",
            "confidence": 0,
            "fish_probability": 0,
            "background_probability": 0,
        }

    first = segments[0]
    probabilities = first.get("probabilities", {})
    return {
        "predicted_class": first.get("predicted_class", "background"),
        "confidence": first.get("confidence", 0),
        "fish_probability": probabilities.get("fish", 0),
        "background_probability": probabilities.get("background", 0),
    }


def _realtime_summary_for_window(session_id, current_analysis=None):
    rows = database.list_realtime_segments(session_id, limit=30)
    if current_analysis:
        rows.append({"status": "analyzed", **current_analysis})
    analyzed = [row for row in rows if row.get("status") == "analyzed"]
    density = calculate_density(analyzed, expected_chunks=30)
    feeding = feeding_from_density(density["density_60s"], density["completeness_60s"])
    return density, feeding
```

- [ ] **Step 5: Add realtime routes in `app.py`**

Add before static file mounting:

```python
@app.post("/api/realtime/sessions")
async def api_create_realtime_session(payload: dict):
    client_id = payload.get("client_id")
    if not client_id:
        raise HTTPException(400, "client_id is required")
    session_id = database.create_realtime_session(
        client_id=client_id,
        name=payload.get("name"),
        chunk_duration=float(payload.get("chunk_duration", 2.0)),
    )
    return database.get_realtime_session(session_id)


@app.post("/api/realtime/sessions/{session_id}/chunks")
async def api_upload_realtime_chunk(session_id: int, file: UploadFile = File(...), metadata: str = Form(...)):
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")

    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid metadata JSON")

    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()
    if meta.get("sha256") and meta["sha256"] != file_hash:
        raise HTTPException(400, "sha256 does not match uploaded file")

    sequence = int(meta["sequence"])
    session_dir = REALTIME_DIR / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{sequence:06d}_{uuid.uuid4().hex}{Path(file.filename).suffix or '.wav'}"
    storage_path = session_dir / storage_name

    try:
        inserted = database.insert_realtime_segment(
            session_id=session_id,
            client_id=meta["client_id"],
            sequence=sequence,
            captured_at=meta["captured_at"],
            duration=float(meta.get("duration", 2.0)),
            sample_rate=int(meta.get("sample_rate", 0)),
            storage_name=str(Path(str(session_id)) / storage_name),
            sha256=file_hash,
        )
    except database.SequenceConflictError:
        return JSONResponse(
            content={"ack": False, "error": "sequence_conflict", "message": "sequence already exists with different sha256"},
            status_code=409,
        )

    if inserted["duplicate"]:
        return {"ack": True, "session_id": session_id, "sequence": sequence, "sha256": file_hash, "duplicate": True, "segment": inserted["row"]}

    with open(storage_path, "wb") as f:
        f.write(content)

    try:
        result = classify_file(str(storage_path))
        if "error" in result:
            database.update_realtime_segment_error(inserted["id"], result["error"])
            return {"ack": True, "session_id": session_id, "sequence": sequence, "sha256": file_hash, "duplicate": False, "segment": {"status": "error", "error": result["error"]}}

        analysis = _chunk_analysis_from_result(result)
        density, feeding = _realtime_summary_for_window(session_id, current_analysis=analysis)
        database.update_realtime_segment_analysis(
            segment_id=inserted["id"],
            predicted_class=analysis["predicted_class"],
            confidence=analysis["confidence"],
            fish_probability=analysis["fish_probability"],
            background_probability=analysis["background_probability"],
            density_60s=density["density_60s"],
            completeness_60s=density["completeness_60s"],
            feeding=feeding,
        )
        segment = database.get_realtime_segment(inserted["id"])
        return {"ack": True, "session_id": session_id, "sequence": sequence, "sha256": file_hash, "duplicate": False, "segment": segment}
    except Exception as e:
        database.update_realtime_segment_error(inserted["id"], str(e))
        return JSONResponse(content={"ack": True, "status": "error", "error": str(e)}, status_code=500)


@app.get("/api/realtime/sessions/{session_id}")
def api_get_realtime_session(session_id: int):
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")
    return session


@app.get("/api/realtime/sessions/{session_id}/segments")
def api_get_realtime_segments(session_id: int, limit: int = 20):
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")
    rows = database.list_realtime_segments(session_id, limit=limit)
    return {"session_id": session_id, "segments": build_latest_sequence_rows(rows, limit=limit)}


@app.post("/api/realtime/sessions/{session_id}/heartbeat")
async def api_realtime_heartbeat(session_id: int, payload: dict):
    ok = database.update_realtime_heartbeat(
        session_id=session_id,
        client_id=payload.get("client_id"),
        last_sequence=int(payload.get("last_sequence", 0)),
        pending_chunks=int(payload.get("pending_chunks", 0)),
        failed_retryable_chunks=int(payload.get("failed_retryable_chunks", 0)),
        failed_conflict_chunks=int(payload.get("failed_conflict_chunks", 0)),
        client_status=payload.get("client_status", "unknown"),
        message=payload.get("message", ""),
    )
    if not ok:
        raise HTTPException(404, "Realtime session not found")
    return {"ack": True, "session_id": session_id, "server_status": database.get_realtime_session(session_id)["status"]}
```

- [ ] **Step 6: Run API tests and fix import issues**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_api
```

Expected: API tests pass. If the local environment lacks `fastapi`, document that and run these tests in the server virtualenv after `pip install -r server/requirements.txt`.

- [ ] **Step 7: Run existing regression tests**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_regressions tests.test_realtime_density tests.test_realtime_database tests.test_realtime_api
```

Expected: all available tests pass in an environment with FastAPI installed.

- [ ] **Step 8: Commit**

```bash
git add server/app.py server/database.py tests/test_realtime_api.py
git commit -m "Add realtime monitoring API"
```

---

### Task 5: Stop Session And Realtime Health Details

**Files:**
- Modify: `server/database.py`
- Modify: `server/app.py`
- Test: `tests/test_realtime_api.py`

- [ ] **Step 1: Add failing tests for stop session and segment placeholders**

Append to `tests/test_realtime_api.py`:

```python
    def test_stop_session_marks_session_stopped(self):
        session = self.client.post("/api/realtime/sessions", json={"client_id": "client-1", "name": "pond-a"}).json()
        res = self.client.post(f"/api/realtime/sessions/{session['id']}/stop")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "stopped")

    def test_segments_endpoint_includes_missing_placeholder(self):
        session = self.client.post("/api/realtime/sessions", json={"client_id": "client-1", "name": "pond-a"}).json()
        import database
        database.insert_realtime_segment(session["id"], "client-1", 1, "2026-04-29 10:00:00", 2.0, 22050, "1.wav", "a")
        database.insert_realtime_segment(session["id"], "client-1", 3, "2026-04-29 10:00:04", 2.0, 22050, "3.wav", "c")
        res = self.client.get(f"/api/realtime/sessions/{session['id']}/segments?limit=3")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([row["sequence"] for row in res.json()["segments"]], [1, 2, 3])
        self.assertEqual(res.json()["segments"][1]["status"], "missing")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_api
```

Expected: stop endpoint is missing.

- [ ] **Step 3: Add database stop helper**

Append to `server/database.py`:

```python
def stop_realtime_session(session_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as db:
        db.execute(
            "UPDATE realtime_sessions SET status='stopped', stopped_at=?, health_status='stopped', health_message='实时监测已停止' WHERE id=?",
            (now, session_id),
        )
        db.commit()
    return get_realtime_session(session_id)
```

- [ ] **Step 4: Add stop route**

Add to `server/app.py`:

```python
@app.post("/api/realtime/sessions/{session_id}/stop")
def api_stop_realtime_session(session_id: int):
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")
    return database.stop_realtime_session(session_id)
```

- [ ] **Step 5: Run API tests and verify GREEN**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_api
```

Expected: all realtime API tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/app.py server/database.py tests/test_realtime_api.py
git commit -m "Add realtime session stop handling"
```

---

### Task 6: Frontend Realtime Page

**Files:**
- Create: `server/static/realtime.html`
- Modify: `server/static/style.css`
- Modify: `server/static/index.html`
- Modify: `server/static/upload.html`
- Modify: `server/static/detail.html`
- Test: `tests/test_realtime_frontend.py`

- [ ] **Step 1: Write failing static frontend tests**

Create `tests/test_realtime_frontend.py`:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"


class RealtimeFrontendTests(unittest.TestCase):
    def test_realtime_page_contains_required_api_calls(self):
        html = (STATIC / "realtime.html").read_text(encoding="utf-8")
        self.assertIn("/api/realtime/sessions", html)
        self.assertIn("/segments?limit=20", html)
        self.assertIn("latest-body", html)
        self.assertIn("timeline", html)

    def test_existing_pages_link_to_realtime(self):
        for page in ["index.html", "upload.html", "detail.html"]:
            html = (STATIC / page).read_text(encoding="utf-8")
            self.assertIn("/realtime.html", html)
            self.assertIn("实时监测", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_frontend
```

Expected: fail because `realtime.html` does not exist and nav links are missing.

- [ ] **Step 3: Add nav links to existing pages**

In `server/static/index.html`, `server/static/upload.html`, and `server/static/detail.html`, add:

```html
<a href="/realtime.html">实时监测</a>
```

Use `class="active"` only in `realtime.html`.

- [ ] **Step 4: Create `realtime.html`**

Create `server/static/realtime.html`:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>实时监测 — Fish Agent</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<nav>
  <a href="/">文件列表</a>
  <a href="/upload.html">上传文件</a>
  <a href="/realtime.html" class="active">实时监测</a>
</nav>

<div class="container">
  <div class="header"><h1>实时鱼声监测</h1></div>

  <div class="card realtime-controls">
    <input id="client-id" value="pond-a-windows-01" placeholder="client_id">
    <input id="session-name" value="pond-a" placeholder="监测名称">
    <button class="btn btn-primary" onclick="startSession()">开始监测</button>
    <button class="btn btn-danger" onclick="stopSession()">停止监测</button>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="label">会话状态</div><div class="value" id="session-status">未开始</div></div>
    <div class="stat-card"><div class="label">连接状态</div><div class="value" id="health-status">等待</div></div>
    <div class="stat-card"><div class="label">60秒鱼声密度</div><div class="value fish" id="density">0%</div></div>
    <div class="stat-card"><div class="label">数据完整度</div><div class="value" id="completeness">0%</div></div>
    <div class="stat-card"><div class="label">投喂建议</div><div class="value high" id="feeding">-</div></div>
  </div>

  <div class="card">
    <h2>最近 20 个分片</h2>
    <div class="timeline" id="timeline"></div>
  </div>

  <div class="card">
    <h2>分片分析</h2>
    <div class="seg-scroll">
      <table>
        <thead>
          <tr><th>序号</th><th>时间</th><th>状态</th><th>预测</th><th>置信度</th><th>鱼声概率</th><th>密度</th><th>建议</th></tr>
        </thead>
        <tbody id="latest-body"><tr><td colspan="8" class="empty">暂无实时分片</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<script>
let sessionId = Number(localStorage.getItem('realtimeSessionId') || 0);
let timer = null;

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

function pct(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

async function startSession() {
  const res = await fetch('/api/realtime/sessions', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      client_id: document.getElementById('client-id').value,
      name: document.getElementById('session-name').value,
      chunk_duration: 2.0
    })
  });
  const data = await res.json();
  sessionId = data.id;
  localStorage.setItem('realtimeSessionId', String(sessionId));
  pollNow();
  startPolling();
}

async function stopSession() {
  if (!sessionId) return;
  await fetch(`/api/realtime/sessions/${sessionId}/stop`, {method: 'POST'});
  pollNow();
  stopPolling();
}

async function pollNow() {
  if (!sessionId) return;
  await Promise.all([loadSummary(), loadSegments()]);
}

function startPolling() {
  stopPolling();
  timer = setInterval(pollNow, 2000);
}

function stopPolling() {
  if (timer) clearInterval(timer);
  timer = null;
}

async function loadSummary() {
  const res = await fetch(`/api/realtime/sessions/${sessionId}`);
  if (!res.ok) return;
  const s = await res.json();
  document.getElementById('session-status').textContent = s.status || '-';
  document.getElementById('health-status').textContent = (s.health_message || s.health_status || '-');
  document.getElementById('density').textContent = pct(s.density_60s);
  document.getElementById('completeness').textContent = pct(s.completeness_60s);
  document.getElementById('feeding').textContent = `${s.feeding_level || '-'} ${s.feeding_amount || 0}kg`;
}

async function loadSegments() {
  const res = await fetch(`/api/realtime/sessions/${sessionId}/segments?limit=20`);
  if (!res.ok) return;
  const data = await res.json();
  renderTimeline(data.segments || []);
  renderTable(data.segments || []);
}

function renderTimeline(rows) {
  const timeline = document.getElementById('timeline');
  timeline.innerHTML = rows.map(row => {
    const cls = row.status === 'missing' ? 'bar-missing' : row.status === 'error' ? 'bar-error' : row.predicted_class === 'fish' ? 'bar-fish' : 'bar-bg';
    const title = `${row.sequence} ${row.status || ''} ${row.predicted_class || ''} ${pct(row.fish_probability)}`;
    return `<div class="bar ${cls}" title="${escapeHtml(title)}"></div>`;
  }).join('');
}

function renderTable(rows) {
  const body = document.getElementById('latest-body');
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">暂无实时分片</td></tr>';
    return;
  }
  body.innerHTML = rows.map(row => `
    <tr>
      <td>${row.sequence}</td>
      <td>${escapeHtml(row.captured_at || '-')}</td>
      <td>${escapeHtml(row.status || '-')}</td>
      <td>${escapeHtml(row.predicted_class || '-')}</td>
      <td>${pct(row.confidence)}</td>
      <td>${pct(row.fish_probability)}</td>
      <td>${pct(row.density_60s)}</td>
      <td>${escapeHtml(row.feeding_message || row.message || '-')}</td>
    </tr>
  `).join('');
}

if (sessionId) {
  pollNow();
  startPolling();
}
</script>
</body>
</html>
```

- [ ] **Step 5: Add realtime CSS**

Append to `server/static/style.css`:

```css
.realtime-controls { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.realtime-controls input { padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px; min-width: 180px; }
.bar-missing { background: #facc15; }
.bar-error { background: #ef4444; }
```

- [ ] **Step 6: Run frontend static tests**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_frontend
```

Expected: frontend static tests pass.

- [ ] **Step 7: Commit**

```bash
git add server/static/realtime.html server/static/style.css server/static/index.html server/static/upload.html server/static/detail.html tests/test_realtime_frontend.py
git commit -m "Add realtime monitoring page"
```

---

### Task 7: Windows Durable Upload Queue

**Files:**
- Create: `windows-acquisition/realtime_uploader.py`
- Test: `tests/test_realtime_uploader.py`

- [ ] **Step 1: Write failing queue tests**

Create `tests/test_realtime_uploader.py`:

```python
import tempfile
import unittest
from pathlib import Path

import sys
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_uploader
```

Expected: fail because `realtime_uploader.py` is missing.

- [ ] **Step 3: Implement queue primitives**

Create `windows-acquisition/realtime_uploader.py`:

```python
"""Reliable realtime chunk upload queue for Fish Agent Windows acquisition."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class QueueItem:
    wav_path: Path
    meta_path: Path
    metadata: dict


class RealtimeQueue:
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, session_id, client_id, sequence, captured_at, sample_rate, duration, wav_bytes):
        session_dir = self.root_dir / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{sequence:06d}"
        wav_path = session_dir / f"{stem}.wav"
        meta_path = session_dir / f"{stem}.json"
        wav_path.write_bytes(wav_bytes)
        metadata = {
            "session_id": session_id,
            "client_id": client_id,
            "sequence": sequence,
            "captured_at": captured_at,
            "sample_rate": sample_rate,
            "duration": duration,
            "sha256": hashlib.sha256(wav_bytes).hexdigest(),
            "state": "pending",
        }
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return QueueItem(wav_path=wav_path, meta_path=meta_path, metadata=metadata)

    def pending_items(self):
        items = []
        for meta_path in sorted(self.root_dir.glob("session_*/*.json")):
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if metadata.get("state") in ("pending", "failed_retryable"):
                wav_path = meta_path.with_suffix(".wav")
                items.append(QueueItem(wav_path=wav_path, meta_path=meta_path, metadata=metadata))
        return items

    def update_state(self, item, state):
        metadata = dict(item.metadata)
        metadata["state"] = state
        item.meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        item.metadata = metadata
```

- [ ] **Step 4: Run queue tests and verify GREEN**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_uploader
```

Expected: queue tests pass.

- [ ] **Step 5: Commit**

```bash
git add windows-acquisition/realtime_uploader.py tests/test_realtime_uploader.py
git commit -m "Add realtime upload queue"
```

---

### Task 8: Windows Realtime Upload Client And Heartbeat

**Files:**
- Modify: `windows-acquisition/realtime_uploader.py`
- Test: `tests/test_realtime_uploader.py`

- [ ] **Step 1: Add failing HTTP client tests**

Append to `tests/test_realtime_uploader.py`:

```python
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
            http = FakeHttp([FakeResponse(200, {"ack": True, "session_id": 1, "sequence": 1, "sha256": item.metadata["sha256"]})])
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
```

Also add `import json` at the top of `tests/test_realtime_uploader.py`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_uploader
```

Expected: fail because `RealtimeUploadClient` is missing.

- [ ] **Step 3: Implement upload client**

Append to `windows-acquisition/realtime_uploader.py`:

```python
import requests


class RealtimeUploadClient:
    def __init__(self, server_url, queue, http=None):
        self.server_url = server_url.rstrip("/")
        self.queue = queue
        self.http = http or requests

    def upload_item(self, item):
        self.queue.update_state(item, "uploading")
        url = f"{self.server_url}/api/realtime/sessions/{item.metadata['session_id']}/chunks"
        try:
            with open(item.wav_path, "rb") as f:
                response = self.http.post(
                    url,
                    data={"metadata": json.dumps({k: v for k, v in item.metadata.items() if k != "state"}, ensure_ascii=False)},
                    files={"file": (item.wav_path.name, f, "audio/wav")},
                    timeout=(10, 120),
                )
        except requests.exceptions.RequestException:
            self.queue.update_state(item, "failed_retryable")
            return False

        if response.status_code == 409:
            self.queue.update_state(item, "failed_conflict")
            return False
        if response.status_code >= 500:
            self.queue.update_state(item, "failed_retryable")
            return False
        if response.status_code >= 400:
            self.queue.update_state(item, "failed_conflict")
            return False

        data = response.json()
        if data.get("ack") and data.get("sha256") == item.metadata.get("sha256"):
            self.queue.update_state(item, "uploaded")
            return True

        self.queue.update_state(item, "failed_retryable")
        return False

    def send_heartbeat(self, session_id, client_id):
        pending = self.queue.pending_items()
        payload = {
            "client_id": client_id,
            "last_sequence": max([item.metadata.get("sequence", 0) for item in pending], default=0),
            "pending_chunks": sum(1 for item in pending if item.metadata.get("state") == "pending"),
            "failed_retryable_chunks": sum(1 for item in pending if item.metadata.get("state") == "failed_retryable"),
            "failed_conflict_chunks": 0,
            "client_status": "uploading_backlog" if pending else "normal",
            "message": "正在补传历史分片" if pending else "实时上传正常",
        }
        return self.http.post(
            f"{self.server_url}/api/realtime/sessions/{session_id}/heartbeat",
            json=payload,
            timeout=(10, 30),
        )
```

- [ ] **Step 4: Run uploader tests**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_uploader
```

Expected: all uploader tests pass.

- [ ] **Step 5: Commit**

```bash
git add windows-acquisition/realtime_uploader.py tests/test_realtime_uploader.py
git commit -m "Add realtime upload client"
```

---

### Task 9: Windows Acquisition Realtime Mode

**Files:**
- Modify: `windows-acquisition/main.py`
- Modify: `windows-acquisition/config.yaml`
- Test: syntax check only unless Windows DAQ test hardware is available.

- [ ] **Step 1: Add realtime config defaults**

Modify `windows-acquisition/config.yaml`:

```yaml
realtime:
  enabled: false
  client_id: "pond-a-windows-01"
  session_name: "pond-a"
  chunk_duration_sec: 2.0
  queue_dir: "D:\\fish_audio\\realtime_queue"
```

- [ ] **Step 2: Add CLI arguments**

Modify `windows-acquisition/main.py` parser:

```python
parser.add_argument("--realtime", action="store_true", help="启用实时分片上传模式")
parser.add_argument("--session-id", type=int, help="已有实时会话 ID")
parser.add_argument("--session-name", default=cfg.get("realtime", {}).get("session_name", "pond-a"), help="实时会话名称")
parser.add_argument("--client-id", default=cfg.get("realtime", {}).get("client_id", "pond-a-windows-01"), help="采集客户端 ID")
parser.add_argument("--queue-dir", default=cfg.get("realtime", {}).get("queue_dir", "D:\\fish_audio\\realtime_queue"), help="实时上传队列目录")
```

- [ ] **Step 3: Add helper to create server session**

Add to `windows-acquisition/realtime_uploader.py`:

```python
def create_session(server_url, client_id, name, chunk_duration=2.0, http=None):
    http = http or requests
    response = http.post(
        f"{server_url.rstrip('/')}/api/realtime/sessions",
        json={"client_id": client_id, "name": name, "chunk_duration": chunk_duration},
        timeout=(10, 30),
    )
    response.raise_for_status()
    return response.json()
```

- [ ] **Step 4: Add realtime loop in `main.py`**

Add a function in `windows-acquisition/main.py`:

```python
def run_realtime_mode(args):
    import threading
    from realtime_uploader import RealtimeQueue, RealtimeUploadClient, create_session

    server_url = upload_cfg["server_url"]
    chunk_duration = cfg.get("realtime", {}).get("chunk_duration_sec", 2.0)
    session_id = args.session_id
    if session_id is None:
        session = create_session(server_url, args.client_id, args.session_name, chunk_duration)
        session_id = session["id"]
        print(f"实时会话已创建: {session_id}")

    queue = RealtimeQueue(args.queue_dir)
    uploader = RealtimeUploadClient(server_url, queue)
    stop_event = threading.Event()
    sequence = 1

    def upload_worker():
        while not stop_event.is_set():
            for item in queue.pending_items():
                uploader.upload_item(item)
            try:
                uploader.send_heartbeat(session_id, args.client_id)
            except Exception as e:
                print(f"heartbeat 失败: {e}")
            time.sleep(2)

    print(f"实时监测启动 | session={session_id} | client={args.client_id}")
    worker = threading.Thread(target=upload_worker, daemon=True)
    worker.start()
    try:
        while True:
            captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            output_path = get_output_path()
            data = acquire_data(chunk_duration)
            save_to_wav(data, SAMPLE_RATE, output_path, WAVE_BIT_DEPTH)
            wav_bytes = Path(output_path).read_bytes()
            queue.enqueue(session_id, args.client_id, sequence, captured_at, SAMPLE_RATE, chunk_duration, wav_bytes)
            print(f"实时分片 {sequence} 已入队 | 待上传: {len(queue.pending_items())}")
            sequence += 1
    except KeyboardInterrupt:
        stop_event.set()
        worker.join(timeout=5)
        print("实时监测已停止")
```

In the `__main__` block after parsing args:

```python
if args.realtime:
    run_realtime_mode(args)
    sys.exit(0)
```

- [ ] **Step 5: Run syntax check**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m py_compile windows-acquisition/main.py windows-acquisition/realtime_uploader.py
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add windows-acquisition/main.py windows-acquisition/config.yaml windows-acquisition/realtime_uploader.py
git commit -m "Add realtime acquisition mode"
```

---

### Task 10: Realtime Replay Tool For Manual Verification

**Files:**
- Create: `server/scripts/replay_realtime.py`
- Test: syntax check and dry-run command.

- [ ] **Step 1: Create replay script**

Create `server/scripts/replay_realtime.py`:

```python
#!/usr/bin/env python3
"""Replay an existing WAV as realtime chunks to a Fish Agent server."""

import argparse
import hashlib
import json
import tempfile
import wave
from datetime import datetime, timedelta
from pathlib import Path

import requests


def create_session(server_url, client_id, name):
    response = requests.post(
        f"{server_url.rstrip('/')}/api/realtime/sessions",
        json={"client_id": client_id, "name": name, "chunk_duration": 2.0},
        timeout=(10, 30),
    )
    response.raise_for_status()
    return response.json()


def iter_wav_chunks(path, chunk_duration):
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frames_per_chunk = int(sample_rate * chunk_duration)
        sequence = 1
        while True:
            frames = wf.readframes(frames_per_chunk)
            if not frames:
                break
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            with wave.open(str(tmp_path), "wb") as out:
                out.setparams((channels, sample_width, sample_rate, len(frames) // sample_width // channels, "NONE", "not compressed"))
                out.writeframes(frames)
            yield sequence, sample_rate, tmp_path
            sequence += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--server", default="http://localhost:8081")
    parser.add_argument("--client-id", default="replay-client")
    parser.add_argument("--name", default="replay-session")
    args = parser.parse_args()

    session = create_session(args.server, args.client_id, args.name)
    start = datetime.now()
    for sequence, sample_rate, chunk_path in iter_wav_chunks(Path(args.file), 2.0):
        content = chunk_path.read_bytes()
        metadata = {
            "client_id": args.client_id,
            "session_id": session["id"],
            "sequence": sequence,
            "captured_at": (start + timedelta(seconds=(sequence - 1) * 2)).strftime("%Y-%m-%d %H:%M:%S"),
            "duration": 2.0,
            "sample_rate": sample_rate,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        response = requests.post(
            f"{args.server.rstrip('/')}/api/realtime/sessions/{session['id']}/chunks",
            data={"metadata": json.dumps(metadata, ensure_ascii=False)},
            files={"file": (chunk_path.name, content, "audio/wav")},
            timeout=(10, 120),
        )
        response.raise_for_status()
        print(f"uploaded sequence={sequence} status={response.json().get('segment', {}).get('status')}")
        chunk_path.unlink(missing_ok=True)

    print(f"Replay complete. Session id: {session['id']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run syntax check**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m py_compile server/scripts/replay_realtime.py
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add server/scripts/replay_realtime.py
git commit -m "Add realtime replay tool"
```

---

### Task 11: Full Verification

**Files:**
- Verify: all realtime backend, frontend, and Windows client files changed by Tasks 1-10.

- [ ] **Step 1: Run all lightweight unit tests**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest discover tests
```

Expected: all tests pass in an environment with server dependencies installed. If FastAPI or requests are missing locally, record the missing module and rerun inside the project virtualenv after installing `server/requirements.txt` and `windows-acquisition/requirements.txt`.

- [ ] **Step 2: Run Python syntax checks**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m py_compile \
  server/app.py \
  server/database.py \
  server/realtime_density.py \
  server/scripts/audio_features.py \
  server/scripts/audio_infer.py \
  server/scripts/preprocess.py \
  server/scripts/replay_realtime.py \
  windows-acquisition/main.py \
  windows-acquisition/uploader.py \
  windows-acquisition/realtime_uploader.py \
  tests/test_regressions.py \
  tests/test_realtime_density.py \
  tests/test_realtime_database.py \
  tests/test_realtime_api.py \
  tests/test_realtime_frontend.py \
  tests/test_realtime_uploader.py
```

Expected: exit 0.

- [ ] **Step 3: Manual server smoke test**

Run from `server/` after installing dependencies:

```bash
python app.py
```

Then check:

```bash
curl -X POST http://localhost:8081/api/realtime/sessions \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"smoke-client","name":"smoke"}'
```

Expected: JSON session with `status` set to `running`.

- [ ] **Step 4: Manual frontend smoke test**

Open:

```text
http://localhost:8081/realtime.html
```

Expected:

- Page loads.
- Start session creates a session.
- Summary cards show running session.
- Latest 20 table starts empty and does not throw console errors.

- [ ] **Step 5: Create a local smoke WAV**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 - <<'PY'
import wave
path = "server/realtime_smoke.wav"
with wave.open(path, "wb") as wf:
    wf.setparams((1, 2, 22050, 44100 * 6, "NONE", "not compressed"))
    wf.writeframes(b"\x00\x00" * 44100 * 6)
print(path)
PY
```

Expected: prints `server/realtime_smoke.wav`.

- [ ] **Step 6: Replay smoke test**

With a WAV file available:

```bash
python server/scripts/replay_realtime.py server/realtime_smoke.wav --server http://localhost:8081
```

Expected:

- Script uploads chunks.
- Realtime page shows timeline blocks and chunk table rows.
- Missing chunks appear if replay is interrupted and resumed.

- [ ] **Step 7: Remove the local smoke WAV**

Run:

```bash
python3 -c "from pathlib import Path; Path('server/realtime_smoke.wav').unlink(missing_ok=True)"
```

Expected: `server/realtime_smoke.wav` is removed.

- [ ] **Step 8: Commit verification fixes**

If verification required fixes to planned files, run:

```bash
git status --short
git add server/app.py server/database.py server/realtime_density.py server/static/realtime.html server/static/style.css windows-acquisition/main.py windows-acquisition/realtime_uploader.py server/scripts/replay_realtime.py tests/test_realtime_density.py tests/test_realtime_database.py tests/test_realtime_api.py tests/test_realtime_frontend.py tests/test_realtime_uploader.py
git commit -m "Stabilize realtime monitoring verification"
```

Expected: commit succeeds only when one or more of those planned files changed during verification. If no fixes were needed, do not create an empty commit.
