"""Reliable realtime chunk upload queue for Fish Agent Windows acquisition."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

REQUEST_EXCEPTIONS = (OSError,)
if requests is not None:
    REQUEST_EXCEPTIONS = (OSError, requests.exceptions.RequestException)


@dataclass
class QueueItem:
    wav_path: Path
    meta_path: Path
    metadata: dict


class RealtimeQueue:
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, session_id, client_id, sequence, captured_at, sample_rate, duration, wav_bytes):
        session_dir = self.root_dir / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{sequence:06d}"
        wav_path = session_dir / f"{stem}.wav"
        meta_path = session_dir / f"{stem}.json"
        wav_path.write_bytes(wav_bytes)
        metadata = {
            "session_id": session_id,
            "client_id": client_id,
            "sequence": sequence,
            "captured_at": captured_at,
            "sample_rate": sample_rate,
            "duration": duration,
            "sha256": hashlib.sha256(wav_bytes).hexdigest(),
            "state": "pending",
        }
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return QueueItem(wav_path=wav_path, meta_path=meta_path, metadata=metadata)

    def pending_items(self):
        items = []
        for meta_path in sorted(self.root_dir.glob("session_*/*.json")):
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if metadata.get("state") in ("pending", "uploading", "failed_retryable"):
                wav_path = meta_path.with_suffix(".wav")
                items.append(QueueItem(wav_path=wav_path, meta_path=meta_path, metadata=metadata))
        return items

    def update_state(self, item, state):
        metadata = dict(item.metadata)
        metadata["state"] = state
        item.meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        item.metadata = metadata


class RealtimeUploadClient:
    def __init__(self, server_url, queue, http=None):
        self.server_url = server_url.rstrip("/")
        self.queue = queue
        if http is None and requests is None:
            raise RuntimeError("缺少 requests 依赖，请先安装: pip install requests")
        self.http = http or requests

    def upload_item(self, item):
        self.queue.update_state(item, "uploading")
        url = f"{self.server_url}/api/realtime/sessions/{item.metadata['session_id']}/chunks"
        payload = {k: v for k, v in item.metadata.items() if k != "state"}

        try:
            with open(item.wav_path, "rb") as f:
                response = self.http.post(
                    url,
                    data={"metadata": json.dumps(payload, ensure_ascii=False)},
                    files={"file": (item.wav_path.name, f, "audio/wav")},
                    timeout=(10, 120),
                )
        except Exception:
            self.queue.update_state(item, "failed_retryable")
            return False

        if response.status_code == 409:
            self.queue.update_state(item, "failed_conflict")
            return False
        if response.status_code >= 500:
            self.queue.update_state(item, "failed_retryable")
            return False
        if response.status_code >= 400 or response.status_code != 200:
            self.queue.update_state(item, "failed_conflict")
            return False

        try:
            data = response.json()
        except ValueError:
            self.queue.update_state(item, "failed_retryable")
            return False

        if (
            data.get("ack")
            and data.get("session_id") == item.metadata.get("session_id")
            and data.get("sequence") == item.metadata.get("sequence")
            and data.get("sha256") == item.metadata.get("sha256")
        ):
            self.queue.update_state(item, "uploaded")
            return True

        self.queue.update_state(item, "failed_retryable")
        return False

    def send_heartbeat(self, session_id, client_id):
        all_items = self._all_items(session_id=session_id)
        pending = [item for item in all_items if item.metadata.get("state") == "pending"]
        retryable = [item for item in all_items if item.metadata.get("state") == "failed_retryable"]
        conflicts = [item for item in all_items if item.metadata.get("state") == "failed_conflict"]
        active_items = pending + retryable + conflicts

        payload = {
            "client_id": client_id,
            "last_sequence": max([item.metadata.get("sequence", 0) for item in all_items], default=0),
            "pending_chunks": len(pending),
            "failed_retryable_chunks": len(retryable),
            "failed_conflict_chunks": len(conflicts),
            "client_status": "uploading_backlog" if active_items else "normal",
            "message": "正在补传历史分片" if active_items else "实时上传正常",
        }
        return self.http.post(
            f"{self.server_url}/api/realtime/sessions/{session_id}/heartbeat",
            json=payload,
            timeout=(10, 30),
        )

    def _all_items(self, session_id=None):
        items = []
        for meta_path in sorted(self.queue.root_dir.glob("session_*/*.json")):
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if session_id is not None and metadata.get("session_id") != session_id:
                continue
            items.append(QueueItem(
                wav_path=meta_path.with_suffix(".wav"),
                meta_path=meta_path,
                metadata=metadata,
            ))
        return items
