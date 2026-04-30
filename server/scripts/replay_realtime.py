#!/usr/bin/env python3
"""Replay an existing WAV as realtime chunks to a Fish Agent server."""

import argparse
import hashlib
import json
import tempfile
import wave
from datetime import datetime, timedelta
from pathlib import Path

import requests


def create_session(server_url, client_id, name):
    response = requests.post(
        f"{server_url.rstrip('/')}/api/realtime/sessions",
        json={"client_id": client_id, "name": name, "chunk_duration": 2.0},
        timeout=(10, 30),
    )
    response.raise_for_status()
    return response.json()


def iter_wav_chunks(path, chunk_duration):
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frames_per_chunk = int(sample_rate * chunk_duration)
        sequence = 1
        while True:
            frames = wf.readframes(frames_per_chunk)
            if not frames:
                break
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            with wave.open(str(tmp_path), "wb") as out:
                frame_count = len(frames) // sample_width // channels
                out.setparams((channels, sample_width, sample_rate, frame_count, "NONE", "not compressed"))
                out.writeframes(frames)
            yield sequence, sample_rate, tmp_path
            sequence += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--server", default="http://localhost:8081")
    parser.add_argument("--client-id", default="replay-client")
    parser.add_argument("--name", default="replay-session")
    args = parser.parse_args()

    session = create_session(args.server, args.client_id, args.name)
    start = datetime.now()
    for sequence, sample_rate, chunk_path in iter_wav_chunks(Path(args.file), 2.0):
        try:
            content = chunk_path.read_bytes()
            metadata = {
                "client_id": args.client_id,
                "session_id": session["id"],
                "sequence": sequence,
                "captured_at": (start + timedelta(seconds=(sequence - 1) * 2)).strftime("%Y-%m-%d %H:%M:%S"),
                "duration": 2.0,
                "sample_rate": sample_rate,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            response = requests.post(
                f"{args.server.rstrip('/')}/api/realtime/sessions/{session['id']}/chunks",
                data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                files={"file": (chunk_path.name, content, "audio/wav")},
                timeout=(10, 120),
            )
            response.raise_for_status()
            print(f"uploaded sequence={sequence} status={response.json().get('segment', {}).get('status')}")
        finally:
            chunk_path.unlink(missing_ok=True)

    print(f"Replay complete. Session id: {session['id']}")


if __name__ == "__main__":
    main()
