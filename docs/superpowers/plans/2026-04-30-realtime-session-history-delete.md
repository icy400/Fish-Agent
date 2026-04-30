# Realtime Session History And Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add realtime session history switching and stopped-session deletion with audio cleanup.

**Architecture:** Extend SQLite helpers for session listing/deletion, expose FastAPI routes that enforce stopped-before-delete and remove `realtime_uploads/{session_id}`, then update the static frontend with a session history table and delete action.

**Tech Stack:** FastAPI, SQLite, Python unittest, static HTML/CSS/JS.

---

### Task 1: Database Session History And Deletion Helpers

**Files:**
- Modify: `server/database.py`
- Test: `tests/test_realtime_database.py`

- [ ] Write failing tests for listing sessions by `client_id`, deleting stopped sessions, and rejecting running-session deletion at the helper level.
- [ ] Implement `list_realtime_sessions_for_client`, `delete_stopped_realtime_session`, and a deletion error type.
- [ ] Run `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest tests.test_realtime_database`.

### Task 2: API Session History And Delete Routes

**Files:**
- Modify: `server/app.py`
- Test: `tests/test_realtime_api.py`

- [ ] Write failing API tests for `GET /api/realtime/clients/{client_id}/sessions` and `DELETE /api/realtime/sessions/{session_id}`.
- [ ] Implement routes, including deletion of `REALTIME_DIR/{session_id}`.
- [ ] Run `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest tests.test_realtime_api`.

### Task 3: Frontend Session History Panel

**Files:**
- Modify: `server/static/realtime.html`
- Modify: `server/static/style.css`
- Test: `tests/test_realtime_frontend.py`

- [ ] Write failing frontend tests for session history markup, history endpoint usage, delete endpoint usage, and delete confirmation.
- [ ] Implement the history table, view action, stopped-only delete action, and panel refresh behavior.
- [ ] Run `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest tests.test_realtime_frontend`.

### Task 4: Final Verification

- [ ] Run `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest discover tests`.
- [ ] Run `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m py_compile server/database.py server/app.py`.
- [ ] Run `git diff --check`.
