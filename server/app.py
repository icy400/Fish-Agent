"""Fish Agent — FastAPI server for acoustic fish feeding analysis."""

import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

import database
from realtime_density import build_latest_sequence_rows, calculate_density, feeding_from_density

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
REALTIME_DIR = Path(os.environ.get("FISH_AGENT_REALTIME_DIR", str(BASE_DIR / "realtime_uploads")))
STATIC_DIR = BASE_DIR / "static"
DB_PATH = os.environ.get("FISH_AGENT_DB_PATH", str(BASE_DIR / "data.db"))

UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)
REALTIME_DIR.mkdir(exist_ok=True)

database.init_db(DB_PATH)

# add scripts to path for inference import
sys.path.insert(0, str(BASE_DIR / "scripts"))
from audio_infer import classify_file

app = FastAPI(title="Fish Agent")

MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807
MAX_SEQUENCE = 10_000_000
MAX_SAMPLE_RATE = 1_000_000
MAX_QUEUE_COUNT = 10_000_000
CLIENT_ONLINE_SECONDS = 10


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


def _realtime_summary_for_window(session_id, current_sequence=None, current_analysis=None):
    rows = database.list_realtime_segments(session_id, limit=30)
    if current_analysis and current_sequence is not None:
        rows = [
            {**row, **current_analysis, "status": "analyzed"}
            if int(row["sequence"]) == int(current_sequence) else row
            for row in rows
        ]
    analyzed = [row for row in rows if row.get("status") == "analyzed"]
    density = calculate_density(analyzed, expected_chunks=30)
    feeding = feeding_from_density(density["density_60s"], density["completeness_60s"])
    return density, feeding


def _realtime_session_response(session):
    density = calculate_density(database.list_realtime_segments(session["id"], limit=30), expected_chunks=30)
    response = dict(session)
    response["missing_count_60s"] = density["missing_count_60s"]
    response["feeding"] = {
        "level": session.get("feeding_level") or "minimal",
        "amount_kg": session.get("feeding_amount") or 0.1,
        "message": session.get("feeding_message") or "数据不足，建议保守处理",
        "confidence": session.get("feeding_confidence") or "insufficient",
    }
    response["health"] = {
        "connection": session.get("health_status") or "waiting",
        "message": session.get("health_message") or "等待实时分片",
    }
    return response


def _realtime_segment_response(segment):
    response = dict(segment)
    response["feeding"] = {
        "level": response.get("feeding_level") or "minimal",
        "amount_kg": response.get("feeding_amount") or 0.1,
        "message": response.get("feeding_message") or "数据不足，建议保守处理",
        "confidence": response.get("feeding_confidence") or "insufficient",
    }
    return response


def _load_realtime_metadata(metadata):
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid metadata JSON")

    for field in ("client_id", "session_id", "sequence", "captured_at", "sha256"):
        if field not in meta:
            raise HTTPException(400, f"{field} is required")
    return meta


def _safe_unlink(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _stored_realtime_path(storage_name):
    path = Path(storage_name)
    if path.is_absolute():
        return path
    return REALTIME_DIR / path


def _int_value(value, field, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(400, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise HTTPException(400, f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise HTTPException(400, f"{field} must be <= {maximum}")
    return value


def _int_metadata(meta, field, default=None, *, minimum=None, maximum=MAX_SQLITE_INTEGER):
    value = meta.get(field, default)
    return _int_value(value, field, minimum=minimum, maximum=maximum)


def _validate_session_id(session_id):
    return _int_value(session_id, "session_id", minimum=1, maximum=MAX_SQLITE_INTEGER)


def _validate_client_id(client_id):
    if not isinstance(client_id, str) or not client_id.strip():
        raise HTTPException(400, "client_id is required")
    if len(client_id) > 128:
        raise HTTPException(400, "client_id must be <= 128 characters")
    return client_id.strip()


def _float_metadata(meta, field, default=None):
    value = meta.get(field, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} must be a number")


def _optional_session_id(payload):
    value = payload.get("current_session_id")
    if value is None:
        return None
    return _int_value(value, "current_session_id", minimum=1, maximum=MAX_SQLITE_INTEGER)


def _client_with_session_response(client):
    session = None
    if client and client.get("current_session_id"):
        found = database.get_realtime_session(client["current_session_id"])
        if found:
            session = _realtime_session_response(found)
    return {"client": client, "session": session}


def _command_action_to_status(action):
    mapping = {
        "ack": "acked",
        "running": "running",
        "complete": "completed",
        "fail": "failed",
    }
    status = mapping.get(action)
    if not status:
        raise HTTPException(404, "Unknown command action")
    return status


# ============================================================
# API routes
# ============================================================

@app.get("/api/files")
def api_list_files(limit: int = 100, offset: int = 0):
    files = database.list_files(limit, offset)
    total = database.count_files()
    return {"total": total, "files": files}


@app.post("/api/files/upload")
async def api_upload(file: UploadFile = File(...), source: str = Form("hydrophone")):
    # read file content
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    # duplicate check
    existing_id = database.get_file_by_hash(file_hash)
    if existing_id is not None:
        existing = database.get_file(existing_id)
        return JSONResponse(content={"id": existing_id, "status": existing["status"], "message": "File already exists.", **existing})

    # save to disk
    ext = Path(file.filename).suffix or ".wav"
    storage_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = UPLOAD_DIR / storage_name
    with open(storage_path, "wb") as f:
        f.write(content)

    # db record
    file_id = database.insert_file(
        original_name=file.filename,
        storage_name=storage_name,
        file_hash=file_hash,
        size_bytes=len(content),
        source=source,
    )

    # run inference synchronously
    try:
        database.update_status(file_id, "analyzing")
        result = classify_file(str(storage_path))

        if "error" in result:
            database.update_status(file_id, "error")
            return JSONResponse(content={"id": file_id, "status": "error", "error": result["error"]})

        # save result JSON
        result_path = RESULT_DIR / f"{file_id}.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # update db
        feeding = result.get("feeding", {})
        database.update_after_inference(
            file_id=file_id,
            fish_count=result["fish_chewing_count"],
            total_segments=result["total_segments"],
            duration=result["total_duration"],
            fish_ratio=result["fish_chewing_ratio"],
            feeding_level=feeding.get("level", ""),
            feeding_amount=feeding.get("amount_kg", 0),
            feeding_message=feeding.get("message", ""),
        )

        return JSONResponse(content={
            "id": file_id,
            "filename": file.filename,
            "status": "analyzed",
            "fish_count": result["fish_chewing_count"],
            "total_segments": result["total_segments"],
            "feeding_level": feeding.get("level", ""),
        })

    except Exception as e:
        database.update_status(file_id, "error")
        return JSONResponse(content={"id": file_id, "status": "error", "error": str(e)}, status_code=500)


@app.get("/api/files/{file_id}")
def api_get_file(file_id: int):
    record = database.get_file(file_id)
    if not record:
        raise HTTPException(404, "File not found")

    # attach inference result if available
    result_path = RESULT_DIR / f"{file_id}.json"
    if result_path.exists():
        with open(result_path, encoding="utf-8") as f:
            record["result"] = json.load(f)
    return record


@app.post("/api/files/{file_id}/analyze")
def api_analyze(file_id: int):
    record = database.get_file(file_id)
    if not record:
        raise HTTPException(404, "File not found")

    storage_path = UPLOAD_DIR / record["storage_name"]
    if not storage_path.exists():
        raise HTTPException(404, "Audio file missing on disk")

    try:
        database.update_status(file_id, "analyzing")
        result = classify_file(str(storage_path))

        if "error" in result:
            database.update_status(file_id, "error")
            return {"status": "error", "error": result["error"]}

        result_path = RESULT_DIR / f"{file_id}.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        feeding = result.get("feeding", {})
        database.update_after_inference(
            file_id=file_id,
            fish_count=result["fish_chewing_count"],
            total_segments=result["total_segments"],
            duration=result["total_duration"],
            fish_ratio=result["fish_chewing_ratio"],
            feeding_level=feeding.get("level", ""),
            feeding_amount=feeding.get("amount_kg", 0),
            feeding_message=feeding.get("message", ""),
        )

        return {"status": "analyzed", "fish_count": result["fish_chewing_count"], "feeding_level": feeding.get("level", "")}

    except Exception as e:
        database.update_status(file_id, "error")
        return {"status": "error", "error": str(e)}


@app.get("/api/files/{file_id}/download")
def api_download(file_id: int):
    record = database.get_file(file_id)
    if not record:
        raise HTTPException(404, "File not found")
    storage_path = UPLOAD_DIR / record["storage_name"]
    if not storage_path.exists():
        raise HTTPException(404, "File missing on disk")
    return FileResponse(storage_path, filename=record["original_name"])


@app.delete("/api/files/{file_id}")
def api_delete(file_id: int):
    record = database.get_file(file_id)
    if not record:
        raise HTTPException(404, "File not found")

    storage_path = UPLOAD_DIR / record["storage_name"]
    if storage_path.exists():
        storage_path.unlink()

    result_path = RESULT_DIR / f"{file_id}.json"
    if result_path.exists():
        result_path.unlink()

    database.delete_file(file_id)
    return {"message": "deleted"}


@app.get("/api/realtime/clients")
def api_list_realtime_clients():
    return {"clients": database.list_realtime_clients(online_seconds=CLIENT_ONLINE_SECONDS)}


@app.get("/api/realtime/clients/{client_id}")
def api_get_realtime_client(client_id: str):
    client_id = _validate_client_id(client_id)
    client = database.get_realtime_client(client_id, online_seconds=CLIENT_ONLINE_SECONDS)
    if not client:
        raise HTTPException(404, "Realtime client not found")
    return _client_with_session_response(client)


@app.get("/api/realtime/clients/{client_id}/sessions")
def api_list_realtime_client_sessions(client_id: str, limit: int = 20):
    client_id = _validate_client_id(client_id)
    limit = _int_value(limit, "limit", minimum=1, maximum=100)
    return {
        "client_id": client_id,
        "sessions": database.list_realtime_sessions_for_client(client_id, limit=limit),
    }


@app.post("/api/realtime/clients/{client_id}/commands/start")
async def api_start_realtime_client(client_id: str, payload: dict):
    client_id = _validate_client_id(client_id)
    chunk_duration = _float_metadata(payload, "chunk_duration", 2.0)
    result = database.enqueue_start_capture_command(
        client_id=client_id,
        session_name=payload.get("session_name") or payload.get("name"),
        chunk_duration=chunk_duration,
    )
    session = database.get_realtime_session(result["session_id"]) if result.get("session_id") else None
    result["session_status"] = session["status"] if session else None
    return result


@app.post("/api/realtime/clients/{client_id}/commands/stop")
def api_stop_realtime_client(client_id: str):
    client_id = _validate_client_id(client_id)
    return database.enqueue_stop_capture_command(client_id)


@app.post("/api/realtime/agents/{client_id}/heartbeat")
async def api_realtime_agent_heartbeat(client_id: str, payload: dict):
    client_id = _validate_client_id(client_id)
    current_session_id = _optional_session_id(payload)
    last_sequence = _int_metadata(payload, "last_sequence", 0, minimum=0, maximum=MAX_SEQUENCE)
    pending_chunks = _int_metadata(payload, "pending_chunks", 0, minimum=0, maximum=MAX_QUEUE_COUNT)
    failed_retryable_chunks = _int_metadata(
        payload, "failed_retryable_chunks", 0, minimum=0, maximum=MAX_QUEUE_COUNT
    )
    failed_conflict_chunks = _int_metadata(
        payload, "failed_conflict_chunks", 0, minimum=0, maximum=MAX_QUEUE_COUNT
    )
    client = database.upsert_realtime_client(
        client_id=client_id,
        name=payload.get("name"),
        status=payload.get("status", "idle"),
        current_session_id=current_session_id,
        agent_version=payload.get("agent_version"),
        sample_rate=_int_metadata(payload, "sample_rate", 0, minimum=0, maximum=MAX_SAMPLE_RATE),
        chunk_duration=_float_metadata(payload, "chunk_duration", 2.0),
        last_sequence=last_sequence,
        pending_chunks=pending_chunks,
        failed_retryable_chunks=failed_retryable_chunks,
        failed_conflict_chunks=failed_conflict_chunks,
        message=payload.get("message", ""),
    )
    if current_session_id:
        session = database.get_realtime_session(current_session_id)
        if session and session["client_id"] == client_id:
            database.update_realtime_heartbeat(
                session_id=current_session_id,
                client_id=client_id,
                last_sequence=last_sequence,
                pending_chunks=pending_chunks,
                failed_retryable_chunks=failed_retryable_chunks,
                failed_conflict_chunks=failed_conflict_chunks,
                client_status=payload.get("status", "idle"),
                message=payload.get("message", ""),
            )
    return {"ack": True, "client": client}


@app.get("/api/realtime/agents/{client_id}/command")
def api_get_realtime_agent_command(client_id: str):
    client_id = _validate_client_id(client_id)
    return {"command": database.get_next_realtime_command(client_id)}


@app.post("/api/realtime/agents/{client_id}/commands/{command_id}/{action}")
async def api_update_realtime_agent_command(client_id: str, command_id: int, action: str, payload: dict = None):
    client_id = _validate_client_id(client_id)
    command_id = _int_value(command_id, "command_id", minimum=1, maximum=MAX_SQLITE_INTEGER)
    status = _command_action_to_status(action)
    payload = payload or {}
    command = database.update_realtime_command_status(
        command_id=command_id,
        client_id=client_id,
        status=status,
        error_message=payload.get("error_message"),
    )
    if not command:
        raise HTTPException(404, "Realtime command not found")
    return {"ack": True, "command": command}


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
    session_id = _validate_session_id(session_id)
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")

    meta = _load_realtime_metadata(metadata)
    if _int_metadata(meta, "session_id", minimum=1) != session_id:
        raise HTTPException(400, "metadata session_id does not match URL")
    if meta["client_id"] != session["client_id"]:
        raise HTTPException(400, "metadata client_id does not match session")

    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()
    if meta["sha256"] != file_hash:
        raise HTTPException(400, "sha256 does not match uploaded file")

    sequence = _int_metadata(meta, "sequence", minimum=1, maximum=MAX_SEQUENCE)
    session_dir = REALTIME_DIR / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{sequence:06d}_{uuid.uuid4().hex}{Path(file.filename or '').suffix or '.wav'}"
    storage_path = session_dir / storage_name

    try:
        with open(storage_path, "wb") as f:
            f.write(content)
    except OSError as e:
        raise HTTPException(500, f"Failed to store realtime chunk: {e}")

    try:
        inserted = database.insert_realtime_segment(
            session_id=session_id,
            client_id=meta["client_id"],
            sequence=sequence,
            captured_at=meta["captured_at"],
            duration=_float_metadata(meta, "duration", 2.0),
            sample_rate=_int_metadata(meta, "sample_rate", 0, minimum=0, maximum=MAX_SAMPLE_RATE),
            storage_name=str(Path(str(session_id)) / storage_name),
            sha256=file_hash,
        )
    except database.SequenceConflictError:
        _safe_unlink(storage_path)
        return JSONResponse(
            content={
                "ack": False,
                "error": "sequence_conflict",
                "message": "sequence already exists with different sha256",
            },
            status_code=409,
        )
    except Exception:
        _safe_unlink(storage_path)
        raise

    if inserted["duplicate"]:
        existing_path = _stored_realtime_path(inserted["row"]["storage_name"])
        if not existing_path.exists():
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            storage_path.replace(existing_path)
        else:
            _safe_unlink(storage_path)
        return {
            "ack": True,
            "session_id": session_id,
            "sequence": sequence,
            "sha256": file_hash,
            "duplicate": True,
            "segment": _realtime_segment_response(inserted["row"]),
        }

    try:
        result = classify_file(str(storage_path))
        if "error" in result:
            database.update_realtime_segment_error(inserted["id"], result["error"])
            return {
                "ack": True,
                "session_id": session_id,
                "sequence": sequence,
                "sha256": file_hash,
                "duplicate": False,
                "segment": {"status": "error", "error": result["error"]},
            }

        analysis = _chunk_analysis_from_result(result)
        density, feeding = _realtime_summary_for_window(
            session_id,
            current_sequence=sequence,
            current_analysis=analysis,
        )
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
        segment = _realtime_segment_response(database.get_realtime_segment(inserted["id"]))
        return {
            "ack": True,
            "session_id": session_id,
            "sequence": sequence,
            "sha256": file_hash,
            "duplicate": False,
            "segment": segment,
        }
    except Exception as e:
        database.update_realtime_segment_error(inserted["id"], str(e))
        return JSONResponse(
            content={
                "ack": True,
                "session_id": session_id,
                "sequence": sequence,
                "sha256": file_hash,
                "duplicate": False,
                "segment": {"status": "error", "error": str(e)},
            }
        )


@app.get("/api/realtime/sessions/{session_id}")
def api_get_realtime_session(session_id: int):
    session_id = _validate_session_id(session_id)
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")
    return _realtime_session_response(session)


@app.delete("/api/realtime/sessions/{session_id}")
def api_delete_realtime_session(session_id: int):
    session_id = _validate_session_id(session_id)
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")
    if session["status"] != "stopped":
        raise HTTPException(409, "Realtime session must be stopped before deletion")

    session_dir = REALTIME_DIR / str(session_id)
    audio_deleted = False
    if session_dir.exists():
        if session_dir.is_dir():
            shutil.rmtree(session_dir)
        else:
            session_dir.unlink()
        audio_deleted = True

    try:
        deleted = database.delete_stopped_realtime_session(session_id)
    except database.RealtimeSessionNotStoppedError as e:
        raise HTTPException(409, str(e))

    return {
        "deleted": bool(deleted),
        "session_id": session_id,
        "audio_deleted": audio_deleted,
    }


@app.get("/api/realtime/sessions/{session_id}/segments")
def api_get_realtime_segments(session_id: int, limit: int = 20):
    session_id = _validate_session_id(session_id)
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")
    rows = database.list_realtime_segments(session_id, limit=limit)
    return {"session_id": session_id, "segments": build_latest_sequence_rows(rows, limit=limit)}


@app.post("/api/realtime/sessions/{session_id}/heartbeat")
async def api_realtime_heartbeat(session_id: int, payload: dict):
    session_id = _validate_session_id(session_id)
    ok = database.update_realtime_heartbeat(
        session_id=session_id,
        client_id=payload.get("client_id"),
        last_sequence=_int_metadata(payload, "last_sequence", 0, minimum=0, maximum=MAX_SEQUENCE),
        pending_chunks=_int_metadata(payload, "pending_chunks", 0, minimum=0, maximum=MAX_QUEUE_COUNT),
        failed_retryable_chunks=_int_metadata(payload, "failed_retryable_chunks", 0, minimum=0, maximum=MAX_QUEUE_COUNT),
        failed_conflict_chunks=_int_metadata(payload, "failed_conflict_chunks", 0, minimum=0, maximum=MAX_QUEUE_COUNT),
        client_status=payload.get("client_status", "unknown"),
        message=payload.get("message", ""),
    )
    if not ok:
        raise HTTPException(404, "Realtime session not found")
    return {
        "ack": True,
        "session_id": session_id,
        "server_status": database.get_realtime_session(session_id)["status"],
    }


@app.post("/api/realtime/sessions/{session_id}/stop")
def api_stop_realtime_session(session_id: int):
    session_id = _validate_session_id(session_id)
    session = database.get_realtime_session(session_id)
    if not session:
        raise HTTPException(404, "Realtime session not found")
    return database.stop_realtime_session(session_id)


# ============================================================
# Static files (must be last)
# ============================================================
@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
