# Multi-Client Frontend-Controlled Realtime Acquisition Design

## Goal

Upgrade realtime fish acoustic monitoring from "Windows client starts capture by itself, browser only watches results" to "browser controls one or more Windows acquisition agents". The browser should list available acquisition clients, start capture on a selected client, watch chunk-level analysis and feeding advice, then stop capture from the same page.

The Windows side becomes a long-running agent. It stays online, sends heartbeat status, polls the server for commands, captures 2-second chunks only when commanded, uploads chunks through the existing reliable queue, and stops capture when the browser sends a stop command.

## Scope

This design covers the first multi-client control version:

- Multiple Windows acquisition clients identified by stable `client_id` values.
- A server-side client registry and command queue.
- Frontend controls for start/stop capture per client.
- Windows `--agent` mode that waits for server commands.
- Current 2-second chunk capture, local queue, upload, inference, density, and feeding logic remain in use.
- Stop capture means "stop producing new chunks"; queued chunks continue uploading.
- Offline clients can receive pending commands after they reconnect.

Out of scope for this pass:

- Browser microphone capture.
- Server-initiated network calls into Windows machines.
- WebSocket command delivery.
- Automatic physical feeder actuation.
- Multi-client aggregate feeding recommendations across several ponds.
- Authentication and role permissions.

## Chosen Architecture

Use server-mediated command polling.

The server is the coordination point. The frontend writes start/stop commands to the server, and each Windows agent periodically asks the server whether it has a command. This avoids requiring inbound network access to Windows machines, which is usually fragile in field deployments with firewalls, NAT, or intermittent connectivity.

The existing realtime upload path remains the data path:

```text
Windows Agent -> POST /api/realtime/sessions/{session_id}/chunks -> inference -> DB -> frontend polling
```

The new control path is:

```text
Frontend -> server command queue -> Windows Agent polling -> command ack/running/completed -> frontend status
```

## Runtime Flow

### Agent Startup

1. Operator starts each Windows computer with:

   ```bash
   python main.py --agent --client-id pond-a-windows-01
   ```

2. Agent sends heartbeat to the server.
3. Server creates or updates the client record.
4. Frontend shows the client as online when recent heartbeat exists.
5. Agent remains idle until it receives a command.

### Start Capture

1. User opens `realtime.html`.
2. Frontend loads all clients from `GET /api/realtime/clients`.
3. User selects one client and clicks start.
4. Frontend calls `POST /api/realtime/clients/{client_id}/commands/start`.
5. Server creates a realtime session for that client, unless the client already has an active session.
6. Server creates a `start_capture` command linked to the session.
7. Agent polls `GET /api/realtime/agents/{client_id}/command`.
8. Agent receives command, ACKs it, and starts capture.
9. Agent captures one 2-second chunk, writes it to the local reliable queue, uploads pending chunks, then captures the next chunk.
10. Frontend polls session summary and segment history as it does today.

### Stop Capture

1. User clicks stop on the selected client.
2. Frontend calls `POST /api/realtime/clients/{client_id}/commands/stop`.
3. Server creates a `stop_capture` command for the active session.
4. Agent polls the command, ACKs it, sets its local stop flag, and finishes the current chunk if one is in progress.
5. Agent stops producing new chunks and marks the command completed.
6. Server marks the realtime session stopped.
7. Agent continues uploading queued chunks until the local queue is clear.

## Data Model

### `realtime_clients`

Tracks Windows acquisition agents.

Fields:

- `client_id` TEXT PRIMARY KEY
- `name` TEXT
- `status` TEXT: `offline`, `idle`, `capturing`, `uploading_backlog`, `error`
- `current_session_id` INTEGER NULL
- `last_heartbeat_at` TEXT
- `last_seen_at` TEXT
- `agent_version` TEXT
- `sample_rate` INTEGER
- `chunk_duration` REAL
- `pending_chunks` INTEGER DEFAULT 0
- `failed_retryable_chunks` INTEGER DEFAULT 0
- `failed_conflict_chunks` INTEGER DEFAULT 0
- `last_sequence` INTEGER DEFAULT 0
- `message` TEXT
- `created_at` TEXT
- `updated_at` TEXT

The server derives "online" from heartbeat freshness. A client whose last heartbeat is too old should display as offline even if the stored `status` is `idle` or `capturing`.

### `realtime_commands`

Durable server-side command queue.

Fields:

- `id` INTEGER PRIMARY KEY
- `client_id` TEXT NOT NULL
- `session_id` INTEGER NULL
- `command_type` TEXT: `start_capture`, `stop_capture`
- `status` TEXT: `pending`, `acked`, `running`, `completed`, `failed`, `cancelled`
- `payload` TEXT JSON
- `created_at` TEXT
- `acked_at` TEXT
- `running_at` TEXT
- `completed_at` TEXT
- `error_message` TEXT

Rules:

- Each client may have only one active pending/acked/running command at a time.
- `start_capture` is idempotent. If the client already has a running session, the server returns that session instead of creating a second one.
- `stop_capture` is idempotent. If no session is running, the server returns a no-op success state.
- A newer stop command may cancel an older pending start command for the same client.

### Existing Tables

`realtime_sessions` remains the monitoring run table. It already has `client_id`, status, density, completeness, feeding, heartbeat, and queue counters. It will continue to store session-level analysis state.

`realtime_segments` remains the chunk analysis table. It continues to use `session_id + sequence` for idempotent chunk uploads.

## API Design

### Frontend APIs

```text
GET /api/realtime/clients
```

Returns all known clients with online/offline status, current session, queue counts, and latest message.

```text
GET /api/realtime/clients/{client_id}
```

Returns one client and its active session summary if present.

```text
POST /api/realtime/clients/{client_id}/commands/start
```

Request:

```json
{
  "session_name": "pond-a",
  "chunk_duration": 2.0
}
```

Response:

```json
{
  "client_id": "pond-a-windows-01",
  "session_id": 12,
  "command_id": 33,
  "command_status": "pending",
  "session_status": "running"
}
```

```text
POST /api/realtime/clients/{client_id}/commands/stop
```

Response:

```json
{
  "client_id": "pond-a-windows-01",
  "session_id": 12,
  "command_id": 34,
  "command_status": "pending"
}
```

The existing session and segment APIs remain:

```text
GET  /api/realtime/sessions/{session_id}
GET  /api/realtime/sessions/{session_id}/segments?limit=20
POST /api/realtime/sessions/{session_id}/chunks
```

### Agent APIs

```text
POST /api/realtime/agents/{client_id}/heartbeat
```

Registers or updates the client. The payload contains current local status, current session id, last sequence, queue counts, sample rate, chunk duration, and message.

```text
GET /api/realtime/agents/{client_id}/command
```

Returns the oldest active command for the client, or:

```json
{
  "command": null
}
```

```text
POST /api/realtime/agents/{client_id}/commands/{command_id}/ack
POST /api/realtime/agents/{client_id}/commands/{command_id}/running
POST /api/realtime/agents/{client_id}/commands/{command_id}/complete
POST /api/realtime/agents/{client_id}/commands/{command_id}/fail
```

These endpoints update command state and client/session state. They are idempotent so the agent can safely retry if the network fails after a server update.

## Windows Agent Behavior

The new `--agent` mode owns the control loop. Existing `--realtime` mode can remain as a manual/debug path.

Agent loop:

1. Send heartbeat every 2 seconds.
2. Poll command every 2 seconds while idle.
3. If `start_capture` arrives, ACK and start capture.
4. During capture:
   - Capture a 2-second chunk.
   - Save chunk to the local queue.
   - Let the upload worker send queued chunks.
   - Check for stop commands between chunks.
5. If `stop_capture` arrives, stop after the current chunk and complete the command.
6. Keep the upload worker alive after capture stops.

Important behavior:

- Capture and upload are decoupled. A slow network should not block new chunk capture.
- The agent should not discard chunks without an ACK that matches `session_id`, `sequence`, and `sha256`.
- If the agent restarts, it scans the queue, resumes uploads, heartbeats its current state, and asks the server for pending commands.
- If the agent restarts while a session was capturing, it should only resume capture if the server still has an active running session and no stop command has completed for it.

## Frontend Design

`realtime.html` becomes a multi-client control page.

Top section:

- Client list or table.
- Each row shows client name, `client_id`, online state, capture state, current session, queue backlog, last heartbeat, and message.
- Row actions: start, stop, view.

Selected client section:

- Current session status.
- Density and completeness for the latest 60-second window.
- Feeding recommendation.
- Recent 20 chunks timeline.
- Recent 20 chunks table with per-chunk class, probability, density, and recommendation.

Polling:

- `GET /api/realtime/clients` every 2 seconds.
- If a client/session is selected, also poll the existing session and segment endpoints.

The UI should make delayed control explicit. If the client is offline and the user clicks stop, the page should show that the stop command is waiting for the client to reconnect.

## Failure Handling

- Client offline before start: server stores a pending start command; frontend displays "waiting for device".
- Client offline before stop: server stores a pending stop command; frontend displays "stop pending".
- Network drops during capture: agent keeps capturing into the local queue; uploads resume later.
- Server unavailable: agent keeps local queue and retries heartbeat/command polling.
- Duplicate start click: server returns the active session and active command instead of creating duplicates.
- Duplicate stop click: server returns the existing pending/running stop command or no-op success if already stopped.
- Command ACK lost: agent retries ACK; server treats repeated ACK as success for the same command.
- Chunk upload conflict: existing 409 behavior remains; client marks the item `failed_conflict`.
- Session stopped with upload backlog: session is stopped for capture, but late chunks from that session are still accepted and analyzed.

## Test Plan

Backend unit tests:

- Client heartbeat creates and updates `realtime_clients`.
- Client list reports online/offline based on heartbeat age.
- Start command creates a session and pending command.
- Repeated start command is idempotent.
- Stop command creates a pending stop for active session.
- Repeated stop command is idempotent.
- Agent command polling returns the correct oldest active command.
- ACK/running/complete/fail endpoints are idempotent.
- Completing stop marks the session stopped.

Windows tests:

- Agent heartbeat payload includes queue counts.
- Agent handles start command and begins capture loop through injectable capture function.
- Agent handles stop command between chunks.
- Upload worker continues after capture stops.
- Restart path scans queue and resumes pending uploads.

Frontend tests:

- Page contains client list controls.
- Start/stop buttons call the new client command endpoints.
- Offline/pending command statuses render safely.
- Existing segment table continues to escape server-provided strings.

Manual verification:

- Run server.
- Run one fake or replay agent as `pond-a-windows-01`.
- Run another fake or replay agent as `pond-b-windows-01`.
- Start and stop each client from the browser independently.
- Confirm chunks and recommendations update only for the selected client's session.

## Rollout Notes

The current `--realtime` mode should remain available for direct manual startup. The new `--agent` mode becomes the recommended production path.

Existing realtime sessions and segments do not need migration beyond adding the new client and command tables. Existing frontend routes stay valid, but `/realtime.html` changes from a single-session page into a device control page.
