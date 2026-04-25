import json
import logging
import random
import subprocess
import time
from collections import deque
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BACKEND_DIR / "config" / "backend_config.json"


def resolve_backend_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (BACKEND_DIR / path).resolve()


def load_config() -> Dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()


def setup_logger() -> logging.Logger:
    log_cfg = CONFIG["logging"]
    log_dir = resolve_backend_path(log_cfg["log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(log_cfg["level"]).upper(), logging.INFO)
    logger = logging.getLogger("fishfeed_backend")
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = TimedRotatingFileHandler(
        filename=log_dir / log_cfg["file_name"],
        when="midnight",
        interval=1,
        backupCount=int(log_cfg["backup_count"]),
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


log = setup_logger()


def _short_text(value: Any, limit: int = 300) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def record_event(level: str, category: str, message: str, **details):
    level_name = str(level or "INFO").upper()
    safe_details = {key: _short_text(value) for key, value in details.items()}
    log_method = getattr(log, level_name.lower(), log.info)
    log_method("%s: %s details=%s", category, message, safe_details)


class AgentHeartbeat(BaseModel):
    deviceId: str = "windows-hydrophone-01"
    running: bool = True
    collecting: bool = False
    uploaderRunning: bool = True
    capturedChunks: int = 0
    message: str = ""
    lastError: str = ""


class AgentControlState:
    def __init__(self):
        agent_cfg = CONFIG["agent_control"]
        self.lock = Lock()
        self.collect_enabled = False
        self.last_command = "STOP"
        self.last_command_at = "-"
        self.last_command_epoch = 0.0
        self.last_heartbeat_at = "-"
        self.last_heartbeat_epoch = 0.0
        self.device_id = "-"
        self.running = False
        self.collecting = False
        self.uploader_running = False
        self.captured_chunks = 0
        self.message = ""
        self.last_error = ""
        self.heartbeat_timeout_seconds = int(agent_cfg["heartbeat_timeout_seconds"])

    def _is_online(self) -> bool:
        if self.last_heartbeat_epoch <= 0:
            return False
        return (time.time() - self.last_heartbeat_epoch) <= self.heartbeat_timeout_seconds

    def control_snapshot(self) -> Dict[str, Any]:
        return {
            "collectEnabled": self.collect_enabled,
            "lastCommand": self.last_command,
            "lastCommandAt": self.last_command_at,
            "serverTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pollHintSeconds": int(CONFIG["agent_control"]["control_poll_hint_seconds"]),
        }

    def status_snapshot(self) -> Dict[str, Any]:
        online = self._is_online()
        return {
            "collectEnabled": self.collect_enabled,
            "lastCommand": self.last_command,
            "lastCommandAt": self.last_command_at,
            "online": online,
            "agentStatus": "在线" if online else "离线",
            "deviceId": self.device_id,
            "running": self.running,
            "collecting": self.collecting,
            "uploaderRunning": self.uploader_running,
            "capturedChunks": self.captured_chunks,
            "message": self.message,
            "lastError": self.last_error,
            "lastHeartbeatAt": self.last_heartbeat_at,
            "heartbeatTimeoutSeconds": self.heartbeat_timeout_seconds,
        }

    def set_collect_enabled(self, enabled: bool):
        self.collect_enabled = enabled
        self.last_command = "START" if enabled else "STOP"
        self.last_command_epoch = time.time()
        self.last_command_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def update_heartbeat(self, hb: AgentHeartbeat):
        self.last_heartbeat_epoch = time.time()
        self.last_heartbeat_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.device_id = hb.deviceId or "-"
        self.running = bool(hb.running)
        self.collecting = bool(hb.collecting)
        self.uploader_running = bool(hb.uploaderRunning)
        self.captured_chunks = int(max(0, hb.capturedChunks))
        self.message = hb.message or ""
        self.last_error = hb.lastError or ""


class RealtimeState:
    def __init__(self):
        rt_cfg = CONFIG["realtime"]
        self.lock = Lock()
        self.running = False
        self.feeding_active = False
        self.start_streak = 0
        self.stop_streak = 0
        self.window = deque(maxlen=int(rt_cfg["decision_window_size"]))
        self.baseline_window = deque(maxlen=int(rt_cfg.get("relative_baseline_window_size", 20)))
        self.judgment_history = deque(maxlen=int(rt_cfg.get("judgment_history_size", 10)))
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
        self.baseline_fish_ratio = 0.0
        self.relative_fish_delta = 0.0
        self.feeding_peak_ratio = 0.0
        self.strategy_reason = "WAIT"

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
            "baselineFishRatio": round(self.baseline_fish_ratio, 4),
            "relativeFishDelta": round(self.relative_fish_delta, 4),
            "feedingPeakRatio": round(self.feeding_peak_ratio, 4),
            "strategyReason": self.strategy_reason,
            "sourceMode": "Windows分片上传",
            "lastChunkAt": self.last_chunk_at,
            "lastChunkName": self.last_chunk_name,
            "lastDeviceId": self.last_device_id,
        }


STATE = RealtimeState()
AGENT_STATE = AgentControlState()
app = FastAPI(title="Fish Feed Simple Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG["cors"]["allow_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
record_event(
    "INFO",
    "system",
    "backend initialized",
    inference_mode=CONFIG["inference"]["mode"],
    log_file=str(resolve_backend_path(CONFIG["logging"]["log_dir"]) / CONFIG["logging"]["file_name"]),
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
    fish_prob_total = 0.0
    for seg in segments:
        confidence_total += float(seg.get("confidence", 0.0))
        probs = seg.get("probabilities", {})
        fish_prob = probs.get("fish")
        if fish_prob is None:
            pred_cls = str(seg.get("predicted_class", "background")).lower()
            conf = float(seg.get("confidence", 0.0))
            fish_prob = conf if pred_cls == "fish" else 1.0 - conf
        fish_prob = max(0.0, min(1.0, float(fish_prob)))
        fish_prob_total += fish_prob
        if fish_prob >= float(rt_cfg["fish_segment_threshold"]):
            fish_segments += 1

    total = len(segments)
    fish_ratio = fish_prob_total / total if total > 0 else 0.0
    confidence = confidence_total / total if total > 0 else float(rt_cfg["default_confidence"])
    return {"fish_ratio": fish_ratio, "confidence": confidence, "fish_segments": fish_segments}


def _infer_python_script(audio_path: Path) -> Dict[str, float]:
    infer_cfg = CONFIG["inference"]
    script_path = Path(infer_cfg["script_path"])
    if not script_path.is_absolute():
        script_path = (Path(__file__).resolve().parent.parent / script_path).resolve()
    if not script_path.exists():
        raise RuntimeError(f"inference script not found: {script_path}")

    cmd = [infer_cfg["python_command"], str(script_path), str(audio_path)]
    record_event("DEBUG", "inference", "python inference started", command=" ".join(cmd), file=audio_path.name)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    merged = (result.stdout or "") + "\n" + (result.stderr or "")
    json_line = None
    for line in merged.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            json_line = line
    if not json_line:
        raise RuntimeError(
            "python script returned no json, "
            f"exit={result.returncode}, stdout={_short_text(result.stdout)}, stderr={_short_text(result.stderr)}"
        )
    payload = json.loads(json_line)
    parsed = _extract_from_python_json(payload)
    record_event(
        "INFO",
        "inference",
        "python inference finished",
        file=audio_path.name,
        fish_ratio=round(parsed["fish_ratio"], 4),
        confidence=round(parsed["confidence"], 4),
        fish_segments=parsed["fish_segments"],
    )
    return parsed


def infer_chunk(audio_path: Path) -> Dict[str, float]:
    mode = str(CONFIG["inference"]["mode"]).lower()
    if mode == "python_script":
        try:
            return _infer_python_script(audio_path)
        except Exception as ex:
            record_event(
                "ERROR",
                "inference",
                "python inference failed; fallback to mock",
                file=audio_path.name,
                error=ex,
            )
            return _infer_mock(audio_path.name)
    record_event("WARNING", "inference", "mock inference mode is active", file=audio_path.name)
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
    baseline_values = list(STATE.baseline_window)
    min_baseline_samples = int(rt_cfg.get("relative_min_baseline_samples", 2))
    relative_enabled = bool(rt_cfg.get("relative_enabled", True))
    baseline_ready = len(baseline_values) >= min_baseline_samples
    baseline_ratio = _window_mean(baseline_values) if baseline_ready else float(rt_cfg.get("relative_default_baseline", 0.0))

    STATE.total_count += max(0, int(fish_segments))
    STATE.fish_ratio = fish_ratio
    STATE.confidence = confidence
    STATE.current_type = "鱼类摄食声" if fish_ratio >= float(rt_cfg["fish_type_threshold"]) else "背景噪音"

    STATE.window.append(fish_ratio)
    STATE.window_fish_ratio = _window_mean(list(STATE.window))
    STATE.baseline_fish_ratio = baseline_ratio
    relative_signal_ratio = max(STATE.window_fish_ratio, fish_ratio)
    STATE.relative_fish_delta = relative_signal_ratio - baseline_ratio

    absolute_start_hit = STATE.window_fish_ratio >= float(rt_cfg["start_threshold"])
    relative_start_hit = (
        relative_enabled
        and baseline_ready
        and relative_signal_ratio >= float(rt_cfg.get("relative_min_start_ratio", 0.08))
        and STATE.relative_fish_delta >= float(rt_cfg.get("relative_start_delta", 0.08))
    )
    start_hit = absolute_start_hit or relative_start_hit

    if start_hit:
        STATE.start_streak += 1
    else:
        STATE.start_streak = 0

    if STATE.feeding_active:
        STATE.feeding_peak_ratio = max(STATE.feeding_peak_ratio, STATE.window_fish_ratio)

    peak_drop = max(0.0, STATE.feeding_peak_ratio - STATE.window_fish_ratio)
    absolute_stop_hit = STATE.window_fish_ratio <= float(rt_cfg["stop_threshold"])
    relative_stop_hit = (
        relative_enabled
        and STATE.feeding_active
        and peak_drop >= float(rt_cfg.get("relative_stop_drop", 0.25))
        and STATE.relative_fish_delta <= float(rt_cfg.get("relative_stop_near_baseline_delta", 0.03))
    )
    stop_hit = absolute_stop_hit or relative_stop_hit

    if stop_hit:
        STATE.stop_streak += 1
    else:
        STATE.stop_streak = 0

    if not STATE.feeding_active:
        if STATE.start_streak >= int(rt_cfg["start_consecutive_windows"]):
            STATE.feeding_active = True
            STATE.decision_action = "FEED_START"
            STATE.feeding_peak_ratio = max(STATE.feeding_peak_ratio, STATE.window_fish_ratio)
            STATE.strategy_reason = "relative_start" if relative_start_hit and not absolute_start_hit else "absolute_start"
        else:
            STATE.decision_action = "WAIT"
            STATE.strategy_reason = "waiting_signal"
    else:
        if STATE.stop_streak >= int(rt_cfg["stop_consecutive_windows"]):
            STATE.feeding_active = False
            STATE.start_streak = 0
            STATE.decision_action = "FEED_STOP"
            STATE.strategy_reason = "relative_stop" if relative_stop_hit and not absolute_stop_hit else "absolute_stop"
            STATE.feeding_peak_ratio = 0.0
        elif (
            STATE.window_fish_ratio <= float(rt_cfg["reduce_threshold"])
            or peak_drop >= float(rt_cfg.get("relative_reduce_drop", 0.15))
        ):
            STATE.decision_action = "FEED_REDUCE"
            STATE.strategy_reason = (
                "relative_reduce"
                if STATE.window_fish_ratio > float(rt_cfg["reduce_threshold"])
                else "absolute_reduce"
            )
        else:
            STATE.decision_action = "FEED_HOLD"
            STATE.strategy_reason = "hold"

    if start_hit:
        STATE.intensity = "高"
    elif STATE.window_fish_ratio >= float(rt_cfg["reduce_threshold"]) or STATE.relative_fish_delta >= float(rt_cfg.get("relative_start_delta", 0.08)) / 2:
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
    STATE.baseline_window.append(fish_ratio)

    STATE.judgment_history.appendleft(
        {
            "time": STATE.last_chunk_at,
            "chunkName": chunk_name,
            "deviceId": STATE.last_device_id,
            "currentType": STATE.current_type,
            "confidence": round(confidence, 4),
            "fishRatio": round(fish_ratio, 4),
            "windowFishRatio": round(STATE.window_fish_ratio, 4),
            "baselineFishRatio": round(STATE.baseline_fish_ratio, 4),
            "relativeFishDelta": round(STATE.relative_fish_delta, 4),
            "feedingPeakRatio": round(STATE.feeding_peak_ratio, 4),
            "fishSegments": int(fish_segments),
            "decisionAction": STATE.decision_action,
            "strategyReason": STATE.strategy_reason,
            "intensity": STATE.intensity,
        }
    )

    if STATE.decision_action != prev_action:
        log.info(
            "action_changed: %s -> %s window_ratio=%.4f baseline=%.4f delta=%.4f reason=%s",
            prev_action,
            STATE.decision_action,
            STATE.window_fish_ratio,
            STATE.baseline_fish_ratio,
            STATE.relative_fish_delta,
            STATE.strategy_reason,
        )

    return STATE.snapshot()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "fishfeed-simple-backend", "time": datetime.now().isoformat()}


@app.get("/realtime/data")
def realtime_data() -> Dict[str, Any]:
    with STATE.lock:
        return STATE.snapshot()


@app.get("/realtime/judgments")
def realtime_judgments() -> Dict[str, Any]:
    with STATE.lock:
        return {"items": list(STATE.judgment_history)}


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
        "relativeEnabled": rt_cfg.get("relative_enabled", True),
        "relativeStartDelta": rt_cfg.get("relative_start_delta", 0.08),
        "relativeBaselineWindowSize": rt_cfg.get("relative_baseline_window_size", 20),
        "uploadDir": str(resolve_backend_path(storage["upload_dir"])),
        "keepUploadedChunks": storage["keep_uploaded_chunks"],
        "pythonCommand": infer_cfg["python_command"],
        "pythonScriptPath": infer_cfg["script_path"],
    }


@app.get("/agent/control")
def agent_control() -> Dict[str, Any]:
    with AGENT_STATE.lock:
        return AGENT_STATE.control_snapshot()


@app.get("/agent/state")
def agent_state() -> Dict[str, Any]:
    with AGENT_STATE.lock:
        return AGENT_STATE.status_snapshot()


@app.post("/agent/heartbeat")
def agent_heartbeat(payload: AgentHeartbeat) -> Dict[str, Any]:
    with AGENT_STATE.lock:
        AGENT_STATE.update_heartbeat(payload)
        snapshot = AGENT_STATE.status_snapshot()
    if payload.lastError:
        record_event("ERROR", "agent", "windows agent heartbeat reported error", device=payload.deviceId, error=payload.lastError)
    elif not payload.uploaderRunning:
        record_event("WARNING", "agent", "windows uploader is not running", device=payload.deviceId, message=payload.message)
    else:
        log.debug(
            "agent_heartbeat: device=%s running=%s collecting=%s uploader=%s chunks=%s",
            payload.deviceId,
            payload.running,
            payload.collecting,
            payload.uploaderRunning,
            payload.capturedChunks,
        )
    return {
        "code": 200,
        "msg": "heartbeat received",
        "collectEnabled": snapshot["collectEnabled"],
        "serverTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/agent/collect/start")
def agent_collect_start() -> Dict[str, Any]:
    with AGENT_STATE.lock:
        AGENT_STATE.set_collect_enabled(True)
        snapshot = AGENT_STATE.status_snapshot()
    record_event("INFO", "agent", "collect command set to START", online=snapshot["online"], device=snapshot["deviceId"])
    return {"code": 200, "msg": "已下发开始采集指令", "data": snapshot}


@app.get("/agent/collect/stop")
def agent_collect_stop() -> Dict[str, Any]:
    with AGENT_STATE.lock:
        AGENT_STATE.set_collect_enabled(False)
        snapshot = AGENT_STATE.status_snapshot()
    record_event("INFO", "agent", "collect command set to STOP", online=snapshot["online"], device=snapshot["deviceId"])
    return {"code": 200, "msg": "已下发停止采集指令", "data": snapshot}


@app.get("/realtime/start")
def realtime_start() -> Dict[str, Any]:
    with STATE.lock:
        STATE.running = True
        STATE.suggestion = "监测已启动，等待上传分片"
        record_event("INFO", "monitor", "monitor started")
        return {"code": 200, "msg": "监测已启动", "data": STATE.snapshot()}


@app.get("/realtime/stop")
def realtime_stop() -> Dict[str, Any]:
    with STATE.lock:
        STATE.running = False
        STATE.feeding_active = False
        STATE.start_streak = 0
        STATE.stop_streak = 0
        STATE.feeding_peak_ratio = 0.0
        STATE.decision_action = "WAIT"
        STATE.strategy_reason = "STOPPED"
        STATE.suggestion = "监测已暂停"
        record_event("INFO", "monitor", "monitor stopped")
        return {"code": 200, "msg": "监测已暂停", "data": STATE.snapshot()}


@app.get("/realtime/reset")
def realtime_reset() -> Dict[str, Any]:
    with STATE.lock:
        default_conf = float(CONFIG["realtime"]["default_confidence"])
        STATE.total_count = 0
        STATE.window.clear()
        STATE.baseline_window.clear()
        STATE.judgment_history.clear()
        STATE.window_fish_ratio = 0.0
        STATE.fish_ratio = 0.0
        STATE.baseline_fish_ratio = 0.0
        STATE.relative_fish_delta = 0.0
        STATE.feeding_peak_ratio = 0.0
        STATE.confidence = default_conf
        STATE.current_type = "背景噪音"
        STATE.intensity = "低"
        STATE.decision_action = "WAIT"
        STATE.strategy_reason = "RESET"
        STATE.suggestion = "统计已重置"
        STATE.start_streak = 0
        STATE.stop_streak = 0
        STATE.feeding_active = False
        record_event("INFO", "monitor", "monitor reset")
        return {"code": 200, "msg": "统计已重置", "data": STATE.snapshot()}


@app.post("/realtime/chunk/upload")
async def chunk_upload(
    file: UploadFile = File(...),
    deviceId: str = Form(default=""),
    collectedAt: str = Form(default=""),
) -> Dict[str, Any]:
    with STATE.lock:
        if not STATE.running:
            record_event("WARNING", "upload", "chunk rejected because monitor is stopped", filename=file.filename, device=deviceId)
            return {"code": 409, "msg": "监测未启动，请先调用 /realtime/start", "data": STATE.snapshot()}

    storage_cfg = CONFIG["storage"]
    upload_dir = resolve_backend_path(storage_cfg["upload_dir"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file.filename.replace(" ", "_")
    chunk_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}"
    save_path = upload_dir / chunk_name

    content = await file.read()
    save_path.write_bytes(content)
    record_event(
        "INFO",
        "upload",
        "chunk received",
        file=chunk_name,
        size=len(content),
        device=deviceId,
        collected_at=collectedAt,
    )

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
        record_event(
            "INFO",
            "strategy",
            "chunk processed",
            file=chunk_name,
            fish_ratio=snapshot["fishRatio"],
            window_ratio=snapshot["windowFishRatio"],
            baseline=snapshot["baselineFishRatio"],
            delta=snapshot["relativeFishDelta"],
            action=snapshot["decisionAction"],
            reason=snapshot["strategyReason"],
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
        record_event("ERROR", "upload", "chunk processing failed", file=chunk_name, error=ex)
        with STATE.lock:
            return {"code": 500, "msg": f"分片识别失败: {ex}", "data": STATE.snapshot()}
    finally:
        if not bool(storage_cfg["keep_uploaded_chunks"]):
            try:
                save_path.unlink(missing_ok=True)
            except Exception:
                record_event("WARNING", "upload", "chunk delete failed", file=save_path)
