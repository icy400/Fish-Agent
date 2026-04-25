#!/usr/bin/env python3
"""
Unified Windows agent:
1) start uploader subprocess
2) poll backend collect command
3) capture audio chunks and write to uploader watch directory
4) report heartbeat to backend
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

import requests

LOGGER = logging.getLogger("fish_windows_agent")


def load_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_path(path_str: str, base_dir: Path) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def setup_logging(cfg: Dict[str, Any], script_dir: Path):
    level_name = str(cfg.get("log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = resolve_path(cfg.get("log_file", "logs/windows_agent.log"), script_dir)
    backup_count = int(cfg.get("log_backup_count", 10))
    log_to_console = bool(cfg.get("log_to_console", True))

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers = []
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    logging.basicConfig(level=level, handlers=handlers)
    LOGGER.info(
        "logging ready: level=%s file=%s rotate=daily backupCount=%s",
        level_name,
        log_file,
        backup_count,
    )


def normalize_base_url(base_url: str) -> str:
    return str(base_url).rstrip("/")


def build_url(cfg: Dict[str, Any], path_key: str) -> str:
    base = normalize_base_url(cfg["server_base_url"])
    path = str(cfg[path_key])
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def load_uploader_watch_dir(cfg: Dict[str, Any], script_dir: Path) -> Path:
    uploader_cfg_path = resolve_path(cfg["uploader_config_path"], script_dir)
    with uploader_cfg_path.open("r", encoding="utf-8") as f:
        uploader_cfg = json.load(f)
    watch_dir = Path(uploader_cfg["watch_dir"])
    return watch_dir


def get_capture_output_dir(cfg: Dict[str, Any], script_dir: Path) -> Path:
    capture_output_dir = str(cfg.get("capture_output_dir", "")).strip()
    if capture_output_dir:
        return Path(capture_output_dir)
    return load_uploader_watch_dir(cfg, script_dir)


def build_chunk_output_path(output_dir: Path, cfg: Dict[str, Any]) -> Path:
    device_id = str(cfg.get("device_id", "windows-hydrophone-01")).replace(" ", "_")
    ext = str(cfg.get("capture_output_extension", ".wav"))
    if not ext.startswith("."):
        ext = "." + ext
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return output_dir / f"{device_id}_{ts}{ext}"


def start_uploader_process(cfg: Dict[str, Any], script_dir: Path) -> Optional[subprocess.Popen]:
    if not bool(cfg.get("enable_uploader", True)):
        LOGGER.warning("uploader disabled by config")
        return None

    uploader_script = resolve_path(cfg["uploader_script_path"], script_dir)
    python_cmd = str(cfg.get("python_command", "python"))
    cmd = [python_cmd, str(uploader_script)]
    LOGGER.info("starting uploader process: %s", " ".join(cmd))
    return subprocess.Popen(cmd, cwd=str(uploader_script.parent))


def start_capture_once(cfg: Dict[str, Any], script_dir: Path, output_path: Path) -> subprocess.Popen:
    capture_script = resolve_path(cfg["capture_script_path"], script_dir)
    python_cmd = str(cfg.get("python_command", "python"))
    chunk_seconds = float(cfg.get("capture_chunk_seconds", 6))
    cmd = [
        python_cmd,
        str(capture_script),
        "--duration-seconds",
        str(chunk_seconds),
        "--auto-start",
    ]
    env = os.environ.copy()
    env_key = str(cfg.get("capture_output_env_var", "HYDROPHONE_WAVE_FILE_PATH"))
    env[env_key] = str(output_path)
    LOGGER.info("starting capture process: %s output=%s", " ".join(cmd), output_path)
    return subprocess.Popen(cmd, cwd=str(capture_script.parent), env=env)


def stop_process(proc: subprocess.Popen, name: str, timeout_seconds: float = 3.0):
    if proc.poll() is not None:
        return
    LOGGER.info("stopping %s process", name)
    proc.terminate()
    try:
        proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        LOGGER.warning("%s process did not exit in time; killing", name)
        proc.kill()
        proc.wait(timeout=timeout_seconds)


def fetch_control(session: requests.Session, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    control_url = build_url(cfg, "control_path")
    timeout = float(cfg.get("request_timeout_seconds", 10))
    try:
        resp = session.get(control_url, timeout=timeout)
        if resp.status_code != 200:
            LOGGER.warning("control poll failed: http=%s", resp.status_code)
            return None
        return resp.json()
    except Exception as ex:
        LOGGER.warning("control poll exception: %s", ex)
        return None


def send_heartbeat(
    session: requests.Session,
    cfg: Dict[str, Any],
    *,
    collecting: bool,
    uploader_running: bool,
    captured_chunks: int,
    message: str,
    last_error: str,
):
    heartbeat_url = build_url(cfg, "heartbeat_path")
    timeout = float(cfg.get("request_timeout_seconds", 10))
    payload = {
        "deviceId": cfg.get("device_id", "windows-hydrophone-01"),
        "running": True,
        "collecting": bool(collecting),
        "uploaderRunning": bool(uploader_running),
        "capturedChunks": int(max(0, captured_chunks)),
        "message": message,
        "lastError": last_error,
    }
    try:
        session.post(heartbeat_url, json=payload, timeout=timeout)
    except Exception as ex:
        LOGGER.warning("heartbeat post exception: %s", ex)


def main():
    script_dir = Path(__file__).resolve().parent
    config_path = script_dir / "agent_config.json"
    if not config_path.exists():
        print(f"[ERROR] config not found: {config_path}")
        return

    cfg = load_config(config_path)
    setup_logging(cfg, script_dir)
    session = requests.Session()

    poll_interval = float(cfg.get("poll_interval_seconds", 1))
    keep_last_command = bool(cfg.get("keep_last_command_on_error", True))
    auto_restart_uploader = bool(cfg.get("auto_restart_uploader", True))
    uploader_restart_wait = float(cfg.get("uploader_restart_wait_seconds", 3))

    output_dir = get_capture_output_dir(cfg, script_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("capture output dir: %s", output_dir)

    uploader_proc = start_uploader_process(cfg, script_dir)
    capture_proc: Optional[subprocess.Popen] = None
    current_output: Optional[Path] = None

    desired_collect = False
    captured_chunks = 0
    last_error = ""
    status_message = "agent started"

    LOGGER.info("agent loop started")
    try:
        while True:
            # Update capture process status.
            if capture_proc is not None and capture_proc.poll() is not None:
                rc = capture_proc.returncode
                if rc == 0 and current_output is not None and current_output.exists():
                    captured_chunks += 1
                    status_message = f"captured chunk: {current_output.name}"
                    LOGGER.info("capture chunk ready: %s", current_output)
                    last_error = ""
                else:
                    status_message = "capture process exited with error"
                    last_error = f"capture exit code={rc}"
                    LOGGER.error("capture failed: returncode=%s output=%s", rc, current_output)
                capture_proc = None
                current_output = None

            # Update uploader process status (and restart if configured).
            uploader_running = False
            if uploader_proc is not None:
                if uploader_proc.poll() is None:
                    uploader_running = True
                else:
                    rc = uploader_proc.returncode
                    LOGGER.error("uploader exited unexpectedly: returncode=%s", rc)
                    status_message = "uploader exited unexpectedly"
                    last_error = f"uploader exit code={rc}"
                    if auto_restart_uploader:
                        time.sleep(uploader_restart_wait)
                        uploader_proc = start_uploader_process(cfg, script_dir)
                        uploader_running = uploader_proc is not None and uploader_proc.poll() is None

            # Pull latest collect command from backend.
            control = fetch_control(session, cfg)
            if control is not None:
                desired_collect = bool(control.get("collectEnabled", False))
                poll_hint = control.get("pollHintSeconds")
                if isinstance(poll_hint, (int, float)) and float(poll_hint) > 0:
                    poll_interval = float(poll_hint)
            elif not keep_last_command:
                desired_collect = False

            # Apply collect command.
            if desired_collect:
                if capture_proc is None:
                    current_output = build_chunk_output_path(output_dir, cfg)
                    try:
                        capture_proc = start_capture_once(cfg, script_dir, current_output)
                        status_message = "capture started"
                    except Exception as ex:
                        capture_proc = None
                        current_output = None
                        status_message = "capture start failed"
                        last_error = str(ex)
                        LOGGER.exception("capture start exception")
            else:
                if capture_proc is not None and capture_proc.poll() is None:
                    stop_process(capture_proc, "capture", timeout_seconds=3.0)
                    capture_proc = None
                    current_output = None
                    status_message = "capture stopped by command"

            send_heartbeat(
                session,
                cfg,
                collecting=desired_collect,
                uploader_running=uploader_running,
                captured_chunks=captured_chunks,
                message=status_message,
                last_error=last_error,
            )
            time.sleep(max(0.2, poll_interval))
    except KeyboardInterrupt:
        LOGGER.info("agent stopped by keyboard interrupt")
    finally:
        if capture_proc is not None:
            stop_process(capture_proc, "capture", timeout_seconds=2.0)
        if uploader_proc is not None:
            stop_process(uploader_proc, "uploader", timeout_seconds=2.0)
        LOGGER.info("agent shutdown complete")


if __name__ == "__main__":
    main()
