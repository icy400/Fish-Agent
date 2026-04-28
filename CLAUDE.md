# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Aquaculture precision feeding system (水产养殖精准投喂系统) — detects fish chewing sounds from hydrophone audio using a TensorFlow Lite binary classifier (fish vs. background) and provides feeding recommendations.

**Architecture:**
- **Windows PC** — DAQ acquisition via BRC2 card, saves WAV, auto-uploads to Linux server
- **Linux Server** — FastAPI backend (inference + API + static file serving), SQLite metadata, pure HTML/JS frontend

## Repo Structure

```
Fish-Agent/
├── windows-acquisition/       # Windows ONLY — DAQ data acquisition
│   ├── main.py                # BRC2.dll driver, capture audio, save WAV, auto-upload
│   ├── uploader.py            # HTTP upload with retry (imported by main.py or run standalone)
│   ├── config.yaml            # DAQ params (sample rate, channel, voltage), server URL
│   └── BRC2.dll, DAQ2.lib, ...
│
├── server/                    # Linux ONLY — inference + API + frontend
│   ├── app.py                 # FastAPI: /api/files/* routes + static file hosting
│   ├── database.py            # SQLite: files table (metadata, status, feeding result)
│   ├── config.json            # Audio/model config (22050Hz, 13 MFCCs, 128 time steps)
│   ├── requirements.txt       # fastapi, uvicorn, numpy, tensorflow, librosa, scipy
│   ├── model/
│   │   └── fish_yamnet.tflite # Binary classifier (1, 128, 13) input
│   ├── scripts/
│   │   ├── audio_infer.py     # Core inference: classify_file() — importable module + CLI
│   │   ├── preprocess.py      # Audio → MFCC features
│   │   ├── train.py           # CNN training
│   │   ├── convert_tflite.py  # Keras .h5 → .tflite
│   │   └── batch_test.py, ...
│   ├── static/                # Pure HTML/JS frontend (zero dependencies)
│   │   ├── index.html         # File list with status badges
│   │   ├── detail.html        # Per-file analysis: stats, timeline, segments table
│   │   └── upload.html        # Drag-and-drop manual upload with progress
│   ├── uploads/               # Stored WAV files (auto-created)
│   └── results/               # Inference JSON per file (auto-created)
```

## Key Architecture

- **Inference**: `app.py` imports `audio_infer.classify_file(filepath)` directly (same Python process, no subprocess). Returns dict with segments, fish count, ratio, and feeding recommendation.
- **Feeding logic** (server-side): ratio >= 0.15 → 0.8kg "high", >= 0.08 → 0.5kg "medium", >= 0.03 → 0.3kg "low", else 0.1kg.
- **Feature extraction**: Always 500Hz 4th-order Butterworth low-pass filter → 13 MFCCs (n_fft=2048, hop_length=512) → pad/truncate to 128 time steps. Input shape: `(1, 128, 13)`.
- **Audio**: 22050Hz sample rate, 2.0s chunk duration, no overlap.
- **Storage**: SQLite for file metadata + status. Inference results (full segments) stored as JSON files in `results/{file_id}.json`.
- **Upload dedup**: Server computes SHA-256 of uploaded file. Duplicates return existing record instead of re-saving.

## Common Commands

### Linux Server

```bash
cd server
pip install -r requirements.txt
python app.py                    # uvicorn on 0.0.0.0:8081
# Or: uvicorn app:app --host 0.0.0.0 --port 8081
```

### API (curl)

```bash
curl -X POST http://localhost:8081/api/files/upload -F "file=@test.wav"
curl http://localhost:8081/api/files              # list
curl http://localhost:8081/api/files/1             # detail + result
curl -X POST http://localhost:8081/api/files/1/analyze  # re-analyze
curl http://localhost:8081/api/files/1/download    # download original
curl -X DELETE http://localhost:8081/api/files/1   # delete
```

### Python inference (standalone)

```bash
cd server
python scripts/audio_infer.py /path/to/audio.wav   # prints JSON to stdout
```

### Windows Acquisition

```bash
cd windows-acquisition
pip install requests pyyaml
python main.py                              # interactive mode
python main.py --duration 3600 --auto-upload  # auto mode
python uploader.py D:\fish_audio\file.wav    # manual upload
```

### ML Training (optional)

```bash
cd server/scripts
python preprocess.py --input data/audio --output data/processed
python train.py --data data/processed --output models/yamnet_finetuned
python convert_tflite.py --model models/yamnet_finetuned/final_model.h5 --output ../model/yamnet.tflite
```
