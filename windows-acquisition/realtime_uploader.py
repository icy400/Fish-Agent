"""Reliable realtime chunk upload queue for Fish Agent Windows acquisition."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


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
            if metadata.get("state") in ("pending", "failed_retryable"):
                wav_path = meta_path.with_suffix(".wav")
                items.append(QueueItem(wav_path=wav_path, meta_path=meta_path, metadata=metadata))
        return items

    def update_state(self, item, state):
        metadata = dict(item.metadata)
        metadata["state"] = state
        item.meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        item.metadata = metadata
