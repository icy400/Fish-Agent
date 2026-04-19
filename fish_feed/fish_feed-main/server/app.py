import os
import tempfile
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scripts.infer import AudioClassifier

BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = os.getenv("FISH_MODEL_PATH", str(BASE_DIR / "models" / "fish_yamnet.tflite"))
LABELS_PATH = os.getenv(
    "FISH_LABELS_PATH", str(BASE_DIR / "models" / "yamnet_finetuned" / "label_encoder.json")
)
WEB_DIR = BASE_DIR / "web"
LOG_FILE_PATH = Path(os.getenv("FISH_SERVER_LOG", str(BASE_DIR / "server_runtime.log")))

logger = logging.getLogger("fish_feed_server")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket connected. active=%s", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket disconnected. active=%s", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


app = FastAPI(title="Fish Feed Live Inference API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = ConnectionManager()
recent_results: list[dict[str, Any]] = []


@app.on_event("startup")
def load_model() -> None:
    if not Path(MODEL_PATH).exists():
        raise FileNotFoundError(f"Model not found: {MODEL_PATH}")

    label_path = LABELS_PATH if Path(LABELS_PATH).exists() else None
    app.state.classifier = AudioClassifier(
        model_path=MODEL_PATH,
        label_encoder_path=label_path,
        sample_rate=22050,
        chunk_duration=2.0,
        overlap=0.5,
    )
    logger.info("Server started. model=%s labels=%s log=%s", MODEL_PATH, label_path, LOG_FILE_PATH)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/results")
def get_results(limit: int = 50) -> dict[str, Any]:
    capped = max(1, min(limit, 500))
    return {"count": len(recent_results[-capped:]), "items": recent_results[-capped:]}


@app.post("/api/v1/analyze")
async def analyze_chunk(
    file: UploadFile = File(...),
    device_id: str = Form("windows-hydrophone-1"),
    chunk_id: str = Form(""),
    timestamp_utc: str = Form(""),
    sample_rate: int = Form(100000),
    channel: int = Form(0),
) -> dict[str, Any]:
    suffix = Path(file.filename or "chunk.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        payload = await file.read()
        tmp.write(payload)
        tmp_path = tmp.name

    try:
        result = app.state.classifier.classify_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    if result is None:
        logger.error("inference failed device=%s chunk=%s", device_id, chunk_id)
        response = {
            "ok": False,
            "error": "inference failed",
            "device_id": device_id,
            "chunk_id": chunk_id,
        }
        return response

    event = {
        "ok": True,
        "device_id": device_id,
        "chunk_id": chunk_id or f"chunk-{int(datetime.now().timestamp() * 1000)}",
        "timestamp_utc": timestamp_utc or datetime.now(timezone.utc).isoformat(),
        "source_sample_rate": sample_rate,
        "source_channel": channel,
        "result": result,
    }

    recent_results.append(event)
    if len(recent_results) > 2000:
        del recent_results[: len(recent_results) - 2000]

    logger.info(
        "inference ok device=%s chunk=%s class=%s conf=%.4f",
        event["device_id"],
        event["chunk_id"],
        result.get("predicted_class"),
        float(result.get("confidence", 0.0)),
    )

    await manager.broadcast(event)
    return event


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise FileNotFoundError("web/index.html not found")
    return FileResponse(index_path)
