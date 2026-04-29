# Real-Time Fish Acoustic Monitoring Design

## Goal

Add a real-time monitoring mode for the aquaculture feeding system. The system should continuously receive 2-second audio chunks from the Windows acquisition client, classify fish chewing sounds on the Linux server, calculate recent fish-sound density, and show both the current feeding recommendation and the latest 20 chunk-level analysis results in the browser.

## Scope

This design covers the first production-ready MVP:

- Windows client captures and uploads 2-second audio chunks.
- Upload survives temporary network/server failures through a local retry queue.
- Server stores monitoring sessions and per-chunk inference results.
- Server computes density-based feeding recommendations.
- Frontend shows current monitoring status, density, recommendation, and the latest 20 chunks.
- The system records missing, duplicate, delayed, and replayed chunks explicitly.

Out of scope for the first version:

- Direct automatic control of a feeder.
- WebSocket raw audio streaming.
- Multi-model ensemble inference.
- Long-term analytics dashboards beyond one session's recent/history view.
- Re-training or changing the TFLite model.

## Chosen Architecture

Use the current Model A direction: Windows acquisition remains the audio source and uploads fixed 2-second chunks over HTTP. The server processes each chunk synchronously on receipt, stores the chunk result, updates session-level density, and exposes polling APIs for the frontend.

This fits the existing codebase because the current inference model already works on 2-second segments, FastAPI already accepts file uploads, and the frontend is plain HTML/JS with no build step. The reliability layer lives mainly on the Windows client as a durable upload queue, while the server provides idempotent chunk ingestion.

## Data Flow

1. User opens `realtime.html` and starts or selects a monitoring session. The Windows client can also create a session when it starts if no session id is provided.
2. Windows client starts `--realtime` mode and creates or resumes a server session.
3. Every 2 seconds, the client saves a chunk WAV and metadata to a local queue.
4. Client attempts upload to `POST /api/realtime/sessions/{session_id}/chunks`.
5. Server validates chunk metadata, deduplicates by `session_id + sequence`, stores the file, runs inference, stores segment result, and returns an ACK.
6. Client marks the queued chunk as uploaded only after receiving a successful ACK.
7. Client periodically sends heartbeat status with local queue counts when the network is available.
8. Frontend polls session summary and latest 20 segments.
9. Frontend displays current density, current feeding recommendation, upload health, and recent chunk history.

## Chunk Identity And Metadata

Every realtime chunk must include stable identity metadata:

```json
{
  "client_id": "pond-a-windows-01",
  "session_id": 1,
  "sequence": 42,
  "captured_at": "2026-04-29 10:32:08",
  "duration": 2.0,
  "sample_rate": 100000,
  "sha256": "hex-file-hash"
}
```

Rules:

- `client_id` identifies the acquisition machine.
- `session_id` identifies a monitoring run.
- `sequence` starts at 1 for each session and increments by 1 per chunk.
- `captured_at` is client capture time and is used for display and gap analysis.
- `sha256` is calculated from the chunk file bytes before upload.
- Server treats `session_id + sequence` as the primary idempotency key.

## Upload Reliability

The Windows client uses a persistent local queue.

Queue behavior:

1. Capture a 2-second chunk.
2. Write the chunk WAV to `realtime_queue/{session_id}/{sequence}.wav`.
3. Write metadata to `realtime_queue/{session_id}/{sequence}.json`.
4. Mark state as `pending`.
5. Attempt upload.
6. On success, mark `uploaded` and optionally move the chunk to `realtime_archive/`.
7. On network/server failure, leave state as `pending` or `failed_retryable`.
8. Continue capturing future chunks even when uploads fail.
9. Retry pending chunks in the background using exponential backoff.
10. On client restart, scan the queue and resume uploading all pending chunks.

Retry schedule:

- First retry after 2 seconds.
- Then 5 seconds.
- Then 10 seconds.
- Then 30 seconds.
- Then every 60 seconds until success or the user stops the session.

Client must not delete a chunk until the server returns an ACK containing the same `session_id`, `sequence`, and `sha256`.

## Server Idempotency And Gap Handling

Server ingestion must be idempotent:

- If `session_id + sequence` does not exist, store and analyze the chunk.
- If `session_id + sequence` exists with the same `sha256`, return the existing result without re-running inference.
- If `session_id + sequence` exists with a different `sha256`, reject with conflict because the client reused a sequence for different audio.
- If chunks arrive out of order, store them by sequence and captured time.
- If a sequence gap is detected, record the missing range in session health.
- If a late chunk fills a gap, update session health and recompute affected density fields.

Missing chunks are represented in the frontend as yellow placeholders in the recent timeline. They do not count as fish or background; they reduce data completeness.

## Density And Feeding Calculation

The first version uses a sliding 60-second density window.

Definitions:

```text
expected_chunks_60s = 30
received_chunks_60s = count of stored chunks captured in the latest 60 seconds
fish_chunks_60s = count of received chunks predicted as fish
density_60s = fish_chunks_60s / received_chunks_60s
completeness_60s = received_chunks_60s / expected_chunks_60s
```

If there are no received chunks in the window, density is `0` and completeness is `0`.

Feeding thresholds reuse the current server logic:

```text
density >= 0.15 -> high, 0.8 kg
density >= 0.08 -> medium, 0.5 kg
density >= 0.03 -> low, 0.3 kg
otherwise       -> minimal, 0.1 kg
```

Recommendation confidence depends on data completeness:

```text
completeness >= 0.80 -> normal recommendation
0.50 <= completeness < 0.80 -> recommendation marked low confidence
completeness < 0.50 -> show "insufficient data"; do not display an aggressive feeding recommendation
```

Each chunk stores the density and recommendation that were current immediately after that chunk was processed. This allows the frontend to show how the recommendation changed across the latest 20 chunks.

## API Design

### Create Session

```text
POST /api/realtime/sessions
```

Request:

```json
{
  "client_id": "pond-a-windows-01",
  "name": "pond-a",
  "chunk_duration": 2.0
}
```

Response:

```json
{
  "id": 1,
  "status": "running",
  "client_id": "pond-a-windows-01",
  "name": "pond-a",
  "created_at": "2026-04-29 10:30:00"
}
```

### Upload Chunk

```text
POST /api/realtime/sessions/{session_id}/chunks
```

Multipart fields:

- `file`: WAV chunk.
- `metadata`: JSON string matching the chunk metadata schema.

Success response:

```json
{
  "ack": true,
  "session_id": 1,
  "sequence": 42,
  "sha256": "hex-file-hash",
  "duplicate": false,
  "segment": {
    "predicted_class": "fish",
    "confidence": 0.91,
    "fish_probability": 0.91,
    "density_60s": 0.18,
    "completeness_60s": 0.93,
    "feeding": {
      "level": "high",
      "amount_kg": 0.8,
      "message": "进食活跃，建议足量投喂",
      "confidence": "normal"
    }
  }
}
```

Conflict response:

```json
{
  "ack": false,
  "error": "sequence_conflict",
  "message": "sequence already exists with different sha256"
}
```

### Session Summary

```text
GET /api/realtime/sessions/{session_id}
```

Response:

```json
{
  "id": 1,
  "status": "running",
  "client_id": "pond-a-windows-01",
  "last_chunk_at": "2026-04-29 10:32:08",
  "density_60s": 0.18,
  "completeness_60s": 0.93,
  "missing_count_60s": 2,
  "client_pending_chunks": 0,
  "client_failed_retryable_chunks": 0,
  "client_failed_conflict_chunks": 0,
  "feeding": {
    "level": "high",
    "amount_kg": 0.8,
    "message": "进食活跃，建议足量投喂",
    "confidence": "normal"
  },
  "health": {
    "connection": "normal",
    "message": "实时监测正常"
  }
}
```

### Client Heartbeat

```text
POST /api/realtime/sessions/{session_id}/heartbeat
```

The Windows client sends heartbeat status when the network is available. This is how the frontend can show local queue pressure such as pending uploads.

Request:

```json
{
  "client_id": "pond-a-windows-01",
  "last_sequence": 42,
  "pending_chunks": 12,
  "failed_retryable_chunks": 3,
  "failed_conflict_chunks": 0,
  "client_status": "uploading_backlog",
  "message": "正在补传历史分片"
}
```

Response:

```json
{
  "ack": true,
  "session_id": 1,
  "server_status": "running"
}
```

If the network is down, heartbeats stop. The server then derives connection health from `last_heartbeat_at` and `last_chunk_at`.

### Latest Segments

```text
GET /api/realtime/sessions/{session_id}/segments?limit=20
```

Response:

```json
{
  "session_id": 1,
  "segments": [
    {
      "sequence": 42,
      "captured_at": "2026-04-29 10:32:08",
      "duration": 2.0,
      "status": "analyzed",
      "predicted_class": "fish",
      "confidence": 0.91,
      "fish_probability": 0.91,
      "density_60s": 0.18,
      "completeness_60s": 0.93,
      "feeding_level": "high",
      "feeding_amount": 0.8,
      "feeding_message": "进食活跃，建议足量投喂"
    }
  ]
}
```

If a recent sequence is missing, the response includes a placeholder:

```json
{
  "sequence": 41,
  "status": "missing",
  "captured_at": null,
  "message": "分片缺失，等待补传"
}
```

### Stop Session

```text
POST /api/realtime/sessions/{session_id}/stop
```

Response:

```json
{
  "id": 1,
  "status": "stopped",
  "stopped_at": "2026-04-29 10:45:00"
}
```

## Database Design

### `realtime_sessions`

Fields:

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `client_id TEXT NOT NULL`
- `name TEXT`
- `status TEXT NOT NULL`
- `chunk_duration REAL DEFAULT 2.0`
- `created_at TEXT NOT NULL`
- `started_at TEXT`
- `stopped_at TEXT`
- `last_chunk_at TEXT`
- `last_heartbeat_at TEXT`
- `client_pending_chunks INTEGER DEFAULT 0`
- `client_failed_retryable_chunks INTEGER DEFAULT 0`
- `client_failed_conflict_chunks INTEGER DEFAULT 0`
- `client_status TEXT DEFAULT 'unknown'`
- `density_60s REAL DEFAULT 0`
- `completeness_60s REAL DEFAULT 0`
- `feeding_level TEXT`
- `feeding_amount REAL DEFAULT 0`
- `feeding_message TEXT`
- `feeding_confidence TEXT DEFAULT 'insufficient'`
- `health_status TEXT DEFAULT 'waiting'`
- `health_message TEXT`

### `realtime_segments`

Fields:

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `session_id INTEGER NOT NULL`
- `client_id TEXT NOT NULL`
- `sequence INTEGER NOT NULL`
- `captured_at TEXT NOT NULL`
- `received_at TEXT NOT NULL`
- `duration REAL NOT NULL`
- `sample_rate INTEGER`
- `storage_name TEXT NOT NULL`
- `sha256 TEXT NOT NULL`
- `status TEXT NOT NULL`
- `predicted_class TEXT`
- `confidence REAL DEFAULT 0`
- `fish_probability REAL DEFAULT 0`
- `background_probability REAL DEFAULT 0`
- `density_60s REAL DEFAULT 0`
- `completeness_60s REAL DEFAULT 0`
- `feeding_level TEXT`
- `feeding_amount REAL DEFAULT 0`
- `feeding_message TEXT`
- `feeding_confidence TEXT`
- `error_message TEXT`

Constraints:

- Unique index on `(session_id, sequence)`.
- Index on `(session_id, captured_at)`.

## Frontend Design

Add `server/static/realtime.html`.

Layout:

1. Navigation tab: `实时监测`.
2. Control row: start session, stop session, session selector.
3. Current status cards:
   - Session status.
   - Connection health.
   - 60-second fish density.
   - Data completeness.
   - Current feeding level and amount.
4. Timeline:
   - 20 blocks.
   - Green for fish, gray for background, yellow for missing, red for error.
   - Color intensity reflects fish probability.
5. Latest 20 chunk table:
   - Sequence.
   - Capture time.
   - Status.
   - Prediction.
   - Confidence.
   - Fish probability.
   - Density at that point.
   - Feeding recommendation at that point.

Polling:

- Poll summary every 2 seconds.
- Poll latest segments every 2 seconds.
- If session is stopped, reduce polling or stop polling.

Frontend must display reliability states plainly:

- `实时监测正常`
- `网络中断，等待补传`
- `正在补传历史分片`
- `数据不足，建议保守处理`
- `服务端分析异常`

## Windows Client Design

Add realtime mode:

```bash
python main.py --realtime --session-name pond-a --client-id pond-a-windows-01
```

Responsibilities:

- Create or resume a server realtime session. If the frontend already created a session, the client receives that `session_id` through config or command line.
- Capture 2-second chunks continuously.
- Store chunk WAV and metadata in a local queue before upload.
- Upload queued chunks in sequence order when possible.
- Retry failed uploads in the background.
- Continue capturing while upload retry is happening.
- Send heartbeat status with queue counts when the network is available.
- Print current upload status and pending queue length.

Local queue files:

```text
D:\fish_audio\realtime_queue\
  session_1\
    000001.wav
    000001.json
    000002.wav
    000002.json
```

Metadata state values:

- `pending`
- `uploading`
- `uploaded`
- `failed_retryable`
- `failed_conflict`

Conflict handling:

- If server returns `sequence_conflict`, mark chunk `failed_conflict`.
- Do not delete conflicted files.
- Print a clear warning so an operator can inspect the queue.

## Error Handling

Server errors:

- Model inference exception: store segment as `error`, keep session running.
- Invalid metadata: return HTTP 400, client marks retry as not useful until metadata is fixed.
- Duplicate chunk same hash: return existing ACK.
- Duplicate chunk different hash: return HTTP 409.
- Session not found: return HTTP 404; client stops uploading that session and asks operator to create/resume.

Client errors:

- Network timeout: keep chunk in queue and retry.
- Server 5xx: retry with backoff.
- Server 409: mark conflict and do not retry automatically.
- Disk write failure: stop realtime capture and report local storage error.

Frontend errors:

- API request failure: show connection issue, keep last known data visible.
- No segments yet: show waiting state.
- Low completeness: show conservative recommendation messaging.

## Testing Strategy

Unit tests:

- Density calculation with all fish, all background, mixed chunks, missing chunks, and empty windows.
- Feeding recommendation confidence based on completeness.
- Server idempotency for duplicate chunk with same hash.
- Server conflict for duplicate chunk with different hash.
- Latest 20 segment response includes missing placeholders.

Integration tests:

- Create session, upload chunks 1-3, fetch summary and latest segments.
- Upload chunk 2 twice and verify no duplicate DB row.
- Upload chunks 1 and 3, verify chunk 2 appears as missing.
- Upload chunk 2 later, verify missing gap is filled.

Manual tests:

- Run server locally.
- Run Windows realtime client against server.
- Disconnect network or stop server for one minute.
- Confirm client keeps capturing and queues chunks.
- Restore connection.
- Confirm queued chunks upload and frontend marks recovery.

## Rollout Plan

Phase 1:

- Implement density module and tests.
- Add DB tables and migration-safe initialization.
- Add realtime session/chunk APIs.

Phase 2:

- Add `realtime.html` with summary cards, timeline, and latest 20 segment table.
- Use polling rather than SSE for simplicity and reliability.

Phase 3:

- Add Windows realtime capture/upload queue mode.
- Add queue retry and startup resume.

Phase 4:

- Replay a long WAV as simulated realtime chunks to verify frontend behavior and density thresholds.
- Test real Windows acquisition with induced network failures.

## Acceptance Criteria

- User can start a realtime monitoring session.
- Windows client can upload 2-second chunks continuously.
- Temporary network failure does not lose chunks.
- Duplicate chunk upload does not create duplicate analysis rows.
- Frontend shows current density and feeding recommendation.
- Frontend shows the latest 20 chunks with per-chunk prediction and recommendation.
- Missing chunks are visible.
- Low data completeness reduces recommendation confidence.
- Session can be stopped and reviewed afterward.
