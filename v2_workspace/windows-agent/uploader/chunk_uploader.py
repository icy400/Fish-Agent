#!/usr/bin/env python3
"""
Windows uploader for Scheme B:
watch local audio chunks and upload them to Linux real-time API.
"""

import json
import logging
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

LOGGER = logging.getLogger("chunk_uploader")


def load_config(config_path: Path):
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def build_upload_url(cfg: dict) -> str:
    base = normalize_base_url(cfg["server_base_url"])
    path = cfg.get("upload_path", "/realtime/chunk/upload")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def get_file_signature(path: Path) -> str:
    stat = path.stat()
    return f"{path.name}|{stat.st_size}|{int(stat.st_mtime)}"


def load_uploaded_record(record_file: Path):
    if not record_file.exists():
        return set()
    with record_file.open("r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def append_uploaded_record(record_file: Path, signature: str):
    record_file.parent.mkdir(parents=True, exist_ok=True)
    with record_file.open("a", encoding="utf-8") as f:
        f.write(signature + "\n")


def collect_pending_files(cfg: dict, uploaded: set):
    watch_dir = Path(cfg["watch_dir"])
    if not watch_dir.exists():
        watch_dir.mkdir(parents=True, exist_ok=True)
        LOGGER.warning("watch_dir not found, created: %s", watch_dir)
        return []

    extensions = {ext.lower() for ext in cfg.get("audio_extensions", [".wav"])}
    files = []
    for path in watch_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        signature = get_file_signature(path)
        if signature in uploaded:
            continue
        files.append(path)

    files.sort(key=lambda p: p.stat().st_mtime)
    return files


def upload_one_file(path: Path, cfg: dict, session: requests.Session) -> bool:
    upload_url = build_upload_url(cfg)
    collected_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    timeout = cfg.get("request_timeout_seconds", 20)

    with path.open("rb") as f:
        files = {"file": (path.name, f, "audio/wav")}
        data = {
            "deviceId": cfg.get("device_id", "windows-hydrophone-01"),
            "collectedAt": collected_at,
        }
        response = session.post(upload_url, files=files, data=data, timeout=timeout)

    if response.status_code != 200:
        LOGGER.error("upload failed: file=%s http=%s", path.name, response.status_code)
        return False

    try:
        body = response.json()
    except Exception:
        LOGGER.error("upload failed: file=%s invalid json response", path.name)
        return False

    code = body.get("code")
    if code != 200:
        LOGGER.error(
            "upload rejected by server: file=%s server_code=%s msg=%s",
            path.name,
            code,
            body.get("msg"),
        )
        return False

    decision = body.get("decisionAction", "-")
    ratio = body.get("windowFishRatio", "-")
    LOGGER.info("upload ok: file=%s decision=%s window_ratio=%s", path.name, decision, ratio)
    return True


def run_loop(cfg: dict):
    record_file = Path(cfg.get("uploaded_record_file", "uploaded_chunks.log"))
    uploaded = load_uploaded_record(record_file)

    scan_interval = cfg.get("scan_interval_seconds", 2)
    max_retries = cfg.get("max_retries", 3)
    retry_backoff = cfg.get("retry_backoff_seconds", 2)
    delete_after_upload = cfg.get("delete_after_upload", True)

    session = requests.Session()
    LOGGER.info("uploader started")
    LOGGER.info("watch_dir=%s", cfg["watch_dir"])
    LOGGER.info("endpoint=%s", build_upload_url(cfg))

    while True:
        pending_files = collect_pending_files(cfg, uploaded)
        if not pending_files:
            time.sleep(scan_interval)
            continue

        for path in pending_files:
            signature = get_file_signature(path)
            success = False
            for attempt in range(1, max_retries + 1):
                try:
                    success = upload_one_file(path, cfg, session)
                    if success:
                        break
                except Exception as ex:
                    LOGGER.exception("upload error: file=%s attempt=%s", path.name, attempt)
                time.sleep(retry_backoff)

            if not success:
                LOGGER.error("give up upload after retries: file=%s", path.name)
                continue

            uploaded.add(signature)
            append_uploaded_record(record_file, signature)

            if delete_after_upload:
                try:
                    path.unlink(missing_ok=True)
                except Exception as ex:
                    LOGGER.warning("delete uploaded file failed: file=%s error=%s", path.name, ex)

        time.sleep(scan_interval)


def setup_logging(cfg: dict, script_dir: Path):
    level_name = str(cfg.get("log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file_name = cfg.get("log_file", "chunk_uploader.log")
    log_file_path = Path(log_file_name)
    if not log_file_path.is_absolute():
        log_file_path = script_dir / log_file_path

    max_bytes = int(cfg.get("log_max_bytes", 10 * 1024 * 1024))
    backup_count = int(cfg.get("log_backup_count", 5))
    log_to_console = bool(cfg.get("log_to_console", True))

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers = []
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=log_file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    logging.basicConfig(level=level, handlers=handlers)
    LOGGER.info(
        "logging ready: level=%s file=%s maxBytes=%s backupCount=%s",
        level_name,
        log_file_path,
        max_bytes,
        backup_count,
    )


def main():
    script_dir = Path(__file__).parent
    config_path = script_dir / "chunk_uploader_config.json"
    if not config_path.exists():
        print(f"[ERROR] config not found: {config_path}")
        return

    cfg = load_config(config_path)
    setup_logging(cfg, script_dir)

    try:
        run_loop(cfg)
    except KeyboardInterrupt:
        LOGGER.info("uploader stopped by keyboard interrupt")
    except Exception:
        LOGGER.exception("uploader crashed")
        raise


if __name__ == "__main__":
    main()
