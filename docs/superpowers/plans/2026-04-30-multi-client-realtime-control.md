# Multi-Client Realtime Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the browser start and stop capture on multiple Windows acquisition agents while keeping the existing realtime chunk upload, analysis, density, and feeding workflow.

**Architecture:** Add server-side client and command tables, expose frontend control APIs and agent polling APIs, add a Windows `--agent` control loop, then replace the realtime page with a multi-client control surface. The Windows agent polls commands, captures only while commanded, and continues uploading queued chunks after capture stops.

**Tech Stack:** FastAPI, SQLite, Python unittest, pure HTML/CSS/JS frontend, Windows Python acquisition client with `requests`.

---

### Task 1: Server Client And Command Persistence

**Files:**
- Modify: `server/database.py`
- Test: `tests/test_realtime_database.py`

- [ ] **Step 1: Write failing database tests**

Add tests for `upsert_realtime_client`, `list_realtime_clients`, `enqueue_start_capture_command`, `enqueue_stop_capture_command`, `get_next_realtime_command`, and `update_realtime_command_status`.

- [ ] **Step 2: Run tests to verify failure**

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest tests.test_realtime_database`

Expected: FAIL because the new database helpers do not exist.

- [ ] **Step 3: Implement tables and helpers**

Create `realtime_clients` and `realtime_commands`, then implement idempotent helper functions for client heartbeat, start/stop command creation, command polling, and command state transitions.

- [ ] **Step 4: Run database tests**

Run the same unittest command. Expected: OK.

- [ ] **Step 5: Commit**

Commit message: `Add realtime client command persistence`

### Task 2: Server Control APIs

**Files:**
- Modify: `server/app.py`
- Test: `tests/test_realtime_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for `GET /api/realtime/clients`, start/stop command endpoints, agent heartbeat, agent command polling, and command ack/running/complete/fail endpoints.

- [ ] **Step 2: Run tests to verify failure**

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest tests.test_realtime_api`

Expected: FAIL with 404 responses for the new routes.

- [ ] **Step 3: Implement FastAPI routes**

Add frontend client APIs and agent APIs, using the database helpers from Task 1. Keep existing session/chunk endpoints compatible.

- [ ] **Step 4: Run API tests**

Run the same unittest command. Expected: OK.

- [ ] **Step 5: Commit**

Commit message: `Add realtime client control API`

### Task 3: Windows Agent Control Client

**Files:**
- Modify: `windows-acquisition/realtime_uploader.py`
- Create: `windows-acquisition/realtime_agent.py`
- Test: `tests/test_realtime_uploader.py`
- Test: `tests/test_realtime_agent.py`

- [ ] **Step 1: Write failing Windows tests**

Add tests for agent heartbeat payloads, command polling, status transitions, start command capture, stop command handling between chunks, and continuing upload after capture stops.

- [ ] **Step 2: Run tests to verify failure**

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_uploader tests.test_realtime_agent`

Expected: FAIL because the agent control helpers and module do not exist.

- [ ] **Step 3: Implement uploader control helpers and pure agent loop**

Add HTTP methods for agent heartbeat, command polling, and command state updates. Implement a pure `RealtimeAgent` class with injectable capture and sleep functions so tests do not require DAQ hardware.

- [ ] **Step 4: Run Windows tests**

Run the same unittest command. Expected: OK.

- [ ] **Step 5: Commit**

Commit message: `Add realtime Windows agent control loop`

### Task 4: Wire `--agent` Into Windows Acquisition

**Files:**
- Modify: `windows-acquisition/main.py`
- Modify: `windows-acquisition/config.yaml`
- Test: syntax checks and agent unit tests

- [ ] **Step 1: Add CLI wiring**

Add `--agent` and related poll interval options, then connect `run_agent_mode` to `RealtimeAgent`.

- [ ] **Step 2: Run syntax and agent tests**

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m py_compile windows-acquisition/main.py windows-acquisition/realtime_agent.py windows-acquisition/realtime_uploader.py`

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m unittest tests.test_realtime_agent tests.test_realtime_uploader`

Expected: OK.

- [ ] **Step 3: Commit**

Commit message: `Wire realtime agent mode`

### Task 5: Frontend Multi-Client Control Page

**Files:**
- Modify: `server/static/realtime.html`
- Modify: `server/static/style.css`
- Test: `tests/test_realtime_frontend.py`

- [ ] **Step 1: Write failing frontend tests**

Assert that `realtime.html` contains client-list rendering, start/stop command endpoint usage, agent status fields, and escaped segment rendering.

- [ ] **Step 2: Run tests to verify failure**

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest tests.test_realtime_frontend`

Expected: FAIL because the page still uses single-session controls.

- [ ] **Step 3: Implement page**

Replace single `client_id` controls with a multi-client table, per-client start/stop/view actions, selected session summary, and recent chunk history.

- [ ] **Step 4: Run frontend tests**

Run the same unittest command. Expected: OK.

- [ ] **Step 5: Commit**

Commit message: `Add multi-client realtime frontend`

### Task 6: Final Verification

**Files:**
- All changed files

- [ ] **Step 1: Run complete tests**

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache /private/tmp/fish-agent-api-venv/bin/python -m unittest discover tests`

Expected: OK.

- [ ] **Step 2: Run compile checks**

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/fish-agent-pycache python3 -m py_compile server/database.py server/app.py windows-acquisition/realtime_uploader.py windows-acquisition/realtime_agent.py windows-acquisition/main.py`

Expected: no output and exit 0.

- [ ] **Step 3: Run whitespace check**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 4: Commit any verification fixes**

Only commit if verification required code changes.
