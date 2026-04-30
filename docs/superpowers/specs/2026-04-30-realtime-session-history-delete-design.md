# Realtime Session History And Deletion Design

## Goal

Add a session history panel to the realtime monitoring page and allow users to delete stopped realtime sessions together with their captured audio chunks.

## Scope

- List recent realtime sessions for a selected `client_id`.
- Switch the current analysis view to a historical session.
- Delete only stopped sessions.
- Delete the session row, related segment rows, related command rows, and audio files under `server/realtime_uploads/{session_id}/`.
- Keep running sessions protected from deletion.

Out of scope:

- Deleting a running session.
- Deleting local queued WAV files on Windows clients.
- User authentication and role-based deletion.

## API

```text
GET /api/realtime/clients/{client_id}/sessions?limit=20
DELETE /api/realtime/sessions/{session_id}
```

The delete endpoint returns HTTP 409 if the session is still running. If the session is stopped, deletion is idempotent with respect to missing audio directories: missing files do not block database cleanup.

## Frontend

`realtime.html` gains a session history table below the client list. Selecting a client loads its recent sessions. Each row has `查看` and `删除` actions. Delete is disabled for running sessions. Deleting the currently viewed session clears the analysis panel.

## Safety

Deletion is server-side authoritative. The frontend hides or disables delete for running sessions, but the backend also enforces `status == "stopped"` before deleting database records or files.
