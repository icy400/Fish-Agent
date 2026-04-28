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

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = str(BASE_DIR / "data.db")

UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)

database.init_db(DB_PATH)

# add scripts to path for inference import
sys.path.insert(0, str(BASE_DIR / "scripts"))
from audio_infer import classify_file

app = FastAPI(title="Fish Agent")


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


# ============================================================
# Static files (must be last)
# ============================================================
@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
