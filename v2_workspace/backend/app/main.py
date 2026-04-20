import json
import logging
import random
import subprocess
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware


def load_config() -> Dict[str, Any]:
    config_path = Path(__file__).resolve().parent.parent / "config" / "backend_config.json"
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()


def setup_logger() -> logging.Logger:
    log_cfg = CONFIG["logging"]
    log_dir = Path(log_cfg["log_dir"]).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(log_cfg["level"]).upper(), logging.INFO)
    logger = logging.getLogger("fishfeed_backend")
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        filename=log_dir / log_cfg["file_name"],
        maxBytes=int(log_cfg["max_bytes"]),
        backupCount=int(log_cfg["backup_count"]),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


log = setup_logger()


class RealtimeState:
    def __init__(self):
        rt_cfg = CONFIG["realtime"]
        self.lock = Lock()
        self.running = False
        self.feeding_active = False
        self.start_streak = 0
        self.stop_streak = 0
        self.window = deque(maxlen=int(rt_cfg["decision_window_size"]))
        self.total_count = 0
        self.last_chunk_name = "-"
        self.last_chunk_at = "-"
        self.last_device_id = "-"
        self.current_type = "背景噪音"
        self.confidence = float(rt_cfg["default_confidence"])
        self.intensity = "低"
        self.suggestion = "等待开始监测"
        self.decision_action = "WAIT"
        self.fish_ratio = 0.0
        self.window_fish_ratio = 0.0

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": "监测中" if self.running else "已暂停",
            "currentType": self.current_type,
            "confidence": round(self.confidence, 4),
            "totalCount": self.total_count,
            "intensity": self.intensity,
            "suggestion": self.suggestion,
            "decisionAction": self.decision_action,
            "fishRatio": round(self.fish_ratio, 4),
            "windowFishRatio": round(self.window_fish_ratio, 4),
            "sourceMode": "Windows分片上传",
            "lastChunkAt": self.last_chunk_at,
            "lastChunkName": self.last_chunk_name,
            "lastDeviceId": self.last_device_id,
        }


STATE = RealtimeState()
app = FastAPI(title="Fish Feed Simple Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG["cors"]["allow_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_round(value: float) -> float:
    return round(float(value), 4)


def _window_mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _infer_mock(file_name: str) -> Dict[str, float]:
    lower_name = file_name.lower()
    if "fish" in lower_name or "chew" in lower_name or "feed" in lower_name:
        fish_ratio = random.uniform(0.45, 0.85)
        confidence = random.uniform(0.70, 0.95)
    else:
        fish_ratio = random.uniform(0.02, 0.30)
        confidence = random.uniform(0.55, 0.85)
    return {"fish_ratio": fish_ratio, "confidence": confidence, "fish_segments": int(round(fish_ratio * 3))}


def _extract_from_python_json(payload: Dict[str, Any]) -> Dict[str, float]:
    rt_cfg = CONFIG["realtime"]
    results = payload.get("results", [])
    if not results:
        return {"fish_ratio": 0.0, "confidence": rt_cfg["default_confidence"], "fish_segments": 0}

    segments = results[0].get("segments", [])
    if not segments:
        return {"fish_ratio": 0.0, "confidence": rt_cfg["default_confidence"], "fish_segments": 0}

    fish_segments = 0
    confidence_total = 0.0
    for seg in segments:
        confidence_total += float(seg.get("confidence", 0.0))
        probs = seg.get("probabilities", {})
        fish_prob = probs.get("fish")
        if fish_prob is None:
            pred_cls = str(seg.get("predicted_class", "background")).lower()
            conf = float(seg.get("confidence", 0.0))
            fish_prob = conf if pred_cls == "fish" else 1.0 - conf
        fish_prob = max(0.0, min(1.0, float(fish_prob)))
        if fish_prob >= float(rt_cfg["fish_segment_threshold"]):
            fish_segments += 1

    total = len(segments)
    fish_ratio = fish_segments / total if total > 0 else 0.0
    confidence = confidence_total / total if total > 0 else float(rt_cfg["default_confidence"])
    return {"fish_ratio": fish_ratio, "confidence": confidence, "fish_segments": fish_segments}


def _infer_python_script(audio_path: Path) -> Dict[str, float]:
    infer_cfg = CONFIG["inference"]
    script_path = Path(infer_cfg["script_path"]).resolve()
    cmd = [infer_cfg["python_command"], str(script_path), str(audio_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    merged = (result.stdout or "") + "\n" + (result.stderr or "")
    json_line = None
    for line in merged.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            json_line = line
    if not json_line:
        raise RuntimeError(f"python script returned no json, exit={result.returncode}")
    payload = json.loads(json_line)
    return _extract_from_python_json(payload)


def infer_chunk(audio_path: Path) -> Dict[str, float]:
    mode = str(CONFIG["inference"]["mode"]).lower()
    if mode == "python_script":
        try:
            return _infer_python_script(audio_path)
        except Exception as ex:
            log.exception("python_script inference failed; fallback to mock: file=%s", audio_path.name)
            return _infer_mock(audio_path.name)
    return _infer_mock(audio_path.name)


def apply_strategy(
    fish_ratio: float,
    confidence: float,
    fish_segments: int,
    device_id: str,
    collected_at: str,
    chunk_name: str,
) -> Dict[str, Any]:
    rt_cfg = CONFIG["realtime"]
    prev_action = STATE.decision_action

    STATE.total_count += max(0, int(fish_segments))
    STATE.fish_ratio = fish_ratio
    STATE.confidence = confidence
    STATE.current_type = "鱼类摄食声" if fish_ratio >= float(rt_cfg["fish_type_threshold"]) else "背景噪音"

    STATE.window.append(fish_ratio)
    STATE.window_fish_ratio = _window_mean(list(STATE.window))

    if STATE.window_fish_ratio >= float(rt_cfg["start_threshold"]):
        STATE.start_streak += 1
    else:
        STATE.start_streak = 0

    if STATE.window_fish_ratio <= float(rt_cfg["stop_threshold"]):
        STATE.stop_streak += 1
    else:
        STATE.stop_streak = 0

    if not STATE.feeding_active:
        if STATE.start_streak >= int(rt_cfg["start_consecutive_windows"]):
            STATE.feeding_active = True
            STATE.decision_action = "FEED_START"
        else:
            STATE.decision_action = "WAIT"
    else:
        if STATE.stop_streak >= int(rt_cfg["stop_consecutive_windows"]):
            STATE.feeding_active = False
            STATE.start_streak = 0
            STATE.decision_action = "FEED_STOP"
        elif STATE.window_fish_ratio <= float(rt_cfg["reduce_threshold"]):
            STATE.decision_action = "FEED_REDUCE"
        else:
            STATE.decision_action = "FEED_HOLD"

    if STATE.window_fish_ratio >= float(rt_cfg["start_threshold"]):
        STATE.intensity = "高"
    elif STATE.window_fish_ratio >= float(rt_cfg["reduce_threshold"]):
        STATE.intensity = "中"
    else:
        STATE.intensity = "低"

    if STATE.decision_action == "FEED_START":
        STATE.suggestion = "检测到持续摄食，建议启动投喂"
    elif STATE.decision_action == "FEED_HOLD":
        STATE.suggestion = "摄食稳定，建议维持当前投喂速率"
    elif STATE.decision_action == "FEED_REDUCE":
        STATE.suggestion = "摄食下降，建议减量投喂"
    elif STATE.decision_action == "FEED_STOP":
        STATE.suggestion = "摄食显著减弱，建议停止投喂"
    else:
        STATE.suggestion = "继续观察，等待更明确的摄食信号"

    STATE.last_chunk_name = chunk_name
    STATE.last_device_id = device_id or "unknown-device"
    STATE.last_chunk_at = collected_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if STATE.decision_action != prev_action:
        log.info(
            "action_changed: %s -> %s window_ratio=%.4f fish_ratio=%.4f",
            prev_action,
            STATE.decision_action,
            STATE.window_fish_ratio,
            STATE.fish_ratio,
        )

    return STATE.snapshot()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "fishfeed-simple-backend", "time": datetime.now().isoformat()}


@app.get("/realtime/data")
def realtime_data() -> Dict[str, Any]:
    with STATE.lock:
        return STATE.snapshot()


@app.get("/realtime/config")
def realtime_config() -> Dict[str, Any]:
    rt_cfg = CONFIG["realtime"]
    storage = CONFIG["storage"]
    infer_cfg = CONFIG["inference"]
    return {
        "mode": CONFIG["inference"]["mode"],
        "chunkSeconds": rt_cfg["chunk_seconds"],
        "decisionWindowSize": rt_cfg["decision_window_size"],
        "startThreshold": rt_cfg["start_threshold"],
        "reduceThreshold": rt_cfg["reduce_threshold"],
        "stopThreshold": rt_cfg["stop_threshold"],
        "uploadDir": str(Path(storage["upload_dir"]).resolve()),
        "keepUploadedChunks": storage["keep_uploaded_chunks"],
        "pythonCommand": infer_cfg["python_command"],
        "pythonScriptPath": infer_cfg["script_path"],
    }


@app.get("/realtime/start")
def realtime_start() -> Dict[str, Any]:
    with STATE.lock:
        STATE.running = True
        STATE.suggestion = "监测已启动，等待上传分片"
        log.info("monitor started")
        return {"code": 200, "msg": "监测已启动", "data": STATE.snapshot()}


@app.get("/realtime/stop")
def realtime_stop() -> Dict[str, Any]:
    with STATE.lock:
        STATE.running = False
        STATE.feeding_active = False
        STATE.start_streak = 0
        STATE.stop_streak = 0
        STATE.decision_action = "WAIT"
        STATE.suggestion = "监测已暂停"
        log.info("monitor stopped")
        return {"code": 200, "msg": "监测已暂停", "data": STATE.snapshot()}


@app.get("/realtime/reset")
def realtime_reset() -> Dict[str, Any]:
    with STATE.lock:
        default_conf = float(CONFIG["realtime"]["default_confidence"])
        STATE.total_count = 0
        STATE.window.clear()
        STATE.window_fish_ratio = 0.0
        STATE.fish_ratio = 0.0
        STATE.confidence = default_conf
        STATE.current_type = "背景噪音"
        STATE.intensity = "低"
        STATE.decision_action = "WAIT"
        STATE.suggestion = "统计已重置"
        STATE.start_streak = 0
        STATE.stop_streak = 0
        STATE.feeding_active = False
        log.info("monitor reset")
        return {"code": 200, "msg": "统计已重置", "data": STATE.snapshot()}


@app.post("/realtime/chunk/upload")
async def chunk_upload(
    file: UploadFile = File(...),
    deviceId: str = Form(default=""),
    collectedAt: str = Form(default=""),
) -> Dict[str, Any]:
    with STATE.lock:
        if not STATE.running:
            return {"code": 409, "msg": "监测未启动，请先调用 /realtime/start", "data": STATE.snapshot()}

    storage_cfg = CONFIG["storage"]
    upload_dir = Path(storage_cfg["upload_dir"]).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file.filename.replace(" ", "_")
    chunk_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}"
    save_path = upload_dir / chunk_name

    content = await file.read()
    save_path.write_bytes(content)
    log.info("chunk_received: file=%s size=%s device=%s collectedAt=%s", chunk_name, len(content), deviceId, collectedAt)

    try:
        infer = infer_chunk(save_path)
        with STATE.lock:
            snapshot = apply_strategy(
                fish_ratio=float(infer["fish_ratio"]),
                confidence=float(infer["confidence"]),
                fish_segments=int(infer["fish_segments"]),
                device_id=deviceId,
                collected_at=collectedAt,
                chunk_name=chunk_name,
            )
        log.info(
            "chunk_processed: file=%s fish_ratio=%.4f window_ratio=%.4f action=%s",
            chunk_name,
            snapshot["fishRatio"],
            snapshot["windowFishRatio"],
            snapshot["decisionAction"],
        )
        return {
            "code": 200,
            "msg": "分片识别成功",
            "data": snapshot,
            "chunkFishRatio": _safe_round(snapshot["fishRatio"]),
            "windowFishRatio": _safe_round(snapshot["windowFishRatio"]),
            "decisionAction": snapshot["decisionAction"],
        }
    except Exception as ex:
        log.exception("chunk_processing_failed: file=%s", chunk_name)
        with STATE.lock:
            return {"code": 500, "msg": f"分片识别失败: {ex}", "data": STATE.snapshot()}
    finally:
        if not bool(storage_cfg["keep_uploaded_chunks"]):
            try:
                save_path.unlink(missing_ok=True)
            except Exception:
                log.warning("chunk_delete_failed: file=%s", save_path)
