"""
Fish acoustic inference — fish chewing vs background classification.
Usage as module:
    from scripts.audio_infer import classify_file
    result = classify_file("/path/to/audio.wav")
Usage as CLI:
    python audio_infer.py /path/to/audio.wav  # prints JSON to stdout
"""

import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

import numpy as np
import tensorflow as tf
import librosa
from scipy import signal as sp_signal

# --- config -----------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "model" / "fish_yamnet.tflite"
CONFIG_PATH = BASE_DIR / "config.json"

CHUNK_DURATION = 2.0
SAMPLE_RATE = 22050
N_MFCC = 13
N_FFT = 2048
HOP_LENGTH = 512
TARGET_LENGTH = 128
LOWPASS_CUTOFF = 500
LOWPASS_ORDER = 4
CLASS_NAMES = ["background", "fish"]

if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    audio = cfg.get("audio_settings", {})
    SAMPLE_RATE = audio.get("sample_rate", SAMPLE_RATE)
    CHUNK_DURATION = audio.get("chunk_duration", CHUNK_DURATION)
    N_MFCC = audio.get("n_mfcc", N_MFCC)
    N_FFT = audio.get("n_fft", N_FFT)
    HOP_LENGTH = audio.get("hop_length", HOP_LENGTH)
    TARGET_LENGTH = audio.get("time_steps", TARGET_LENGTH)
    CLASS_NAMES = cfg.get("classes", CLASS_NAMES)

# --- lazy model loading ------------------------------------------------
_interpreter = None
_input_details = None
_output_details = None


def _load_model():
    global _interpreter, _input_details, _output_details
    if _interpreter is not None:
        return _interpreter, _input_details, _output_details
    _interpreter = tf.lite.Interpreter(model_path=str(MODEL_PATH))
    _interpreter.allocate_tensors()
    _input_details = _interpreter.get_input_details()
    _output_details = _interpreter.get_output_details()
    return _interpreter, _input_details, _output_details


def butter_lowpass_filter(data, cutoff=LOWPASS_CUTOFF, fs=SAMPLE_RATE, order=LOWPASS_ORDER):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    sos = sp_signal.butter(order, normal_cutoff, btype="low", output="sos")
    return sp_signal.sosfilt(sos, data)


def _classify_chunk(audio_chunk, sr):
    interpreter, input_details, output_details = _load_model()
    audio_chunk = butter_lowpass_filter(audio_chunk, cutoff=LOWPASS_CUTOFF, fs=sr)
    mfccs = librosa.feature.mfcc(y=audio_chunk, sr=sr, n_mfcc=N_MFCC, n_fft=N_FFT, hop_length=HOP_LENGTH)
    if mfccs.shape[1] < TARGET_LENGTH:
        mfccs = np.pad(mfccs, ((0, 0), (0, TARGET_LENGTH - mfccs.shape[1])), mode="constant")
    else:
        mfccs = mfccs[:, :TARGET_LENGTH]

    features = mfccs.T.astype(np.float32)
    features = np.expand_dims(features, axis=0)

    interpreter.set_tensor(input_details[0]["index"], features)
    interpreter.invoke()
    output_data = interpreter.get_tensor(output_details[0]["index"])[0]
    idx = np.argmax(output_data)
    conf = float(output_data[idx])

    return {
        "predicted_class": CLASS_NAMES[idx],
        "confidence": round(conf, 4),
        "probabilities": {CLASS_NAMES[i]: round(float(output_data[i]), 4) for i in range(len(CLASS_NAMES))},
    }


def _merge_segments(seg_list):
    if not seg_list:
        return []
    merged = []
    cur = {"time_start": seg_list[0]["time_start"], "time_end": seg_list[0]["time_end"]}
    for seg in seg_list[1:]:
        if seg["time_start"] - cur["time_end"] <= 0.1:
            cur["time_end"] = seg["time_end"]
        else:
            merged.append(cur)
            cur = seg.copy()
    merged.append(cur)
    return merged


def classify_file(filepath):
    """Classify an audio file. Returns dict with full results."""
    audio_path = Path(filepath)
    if not audio_path.exists():
        return {"error": f"file not found: {filepath}"}

    y, sr = librosa.load(str(audio_path), sr=SAMPLE_RATE)
    duration = len(y) / sr
    chunk_samples = int(sr * CHUNK_DURATION)
    results = []

    if len(y) >= chunk_samples:
        for start in range(0, len(y) - chunk_samples + 1, chunk_samples):
            chunk = y[start : start + chunk_samples]
            res = _classify_chunk(chunk, sr)
            if res:
                results.append({
                    "time_start": round(start / sr, 2),
                    "time_end": round((start + chunk_samples) / sr, 2),
                    **res,
                })

    fish_segments = [s for s in results if s["predicted_class"] == "fish"]
    bg_segments = [s for s in results if s["predicted_class"] == "background"]

    fish_count = len(fish_segments)
    total = len(results)
    ratio = fish_count / total if total > 0 else 0

    # feeding recommendation
    if ratio >= 0.15:
        amount, level, msg = 0.8, "high", "进食活跃，建议足量投喂"
    elif ratio >= 0.08:
        amount, level, msg = 0.5, "medium", "进食正常，建议标准投喂"
    elif ratio >= 0.03:
        amount, level, msg = 0.3, "low", "进食一般，建议少量投喂"
    else:
        amount, level, msg = 0.1, "minimal", "进食较弱，建议不投喂或极少量"

    return {
        "filename": audio_path.name,
        "total_duration": round(duration, 2),
        "total_segments": total,
        "fish_chewing_count": fish_count,
        "fish_chewing_ratio": round(ratio, 4),
        "fish_chewing_segments": _merge_segments(fish_segments),
        "background_segments": _merge_segments(bg_segments),
        "segments": results,
        "feeding": {
            "amount_kg": amount,
            "level": level,
            "message": msg,
        },
        "model": "fish_yamnet.tflite",
        "inference_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# --- CLI ---------------------------------------------------------------
if __name__ == "__main__":
    sys.stderr = open(os.devnull, "w")
    if len(sys.argv) < 2:
        sys.stdout = sys.__stdout__
        print(json.dumps({"error": "usage: python audio_infer.py <audio_file>"}))
        sys.exit(1)

    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        sys.stdout = sys.__stdout__
        print(json.dumps({"error": f"file not found: {audio_path}"}, ensure_ascii=False))
        sys.exit(1)

    try:
        result = classify_file(str(audio_path))
        sys.stdout = sys.__stdout__
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        sys.stdout = sys.__stdout__
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
