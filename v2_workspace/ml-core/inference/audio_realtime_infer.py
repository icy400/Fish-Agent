import os
import sys
import json
import warnings

# ================== 【核心修改】屏蔽所有 TensorFlow 和 Python 警告 ==================
# 1. 屏蔽 Python 的 UserWarning (比如 interpreter 弃用警告)
warnings.filterwarnings("ignore")

# 2. 屏蔽 TensorFlow 的 C++ 日志 (必须在 import tensorflow 之前设置)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'

# 3. 将标准错误输出重定向到空设备 (彻底屏蔽 STDERR)
sys.stderr = open(os.devnull, 'w')
# ==============================================================================

# 导入库 (放在屏蔽代码之后)
import numpy as np
import tensorflow as tf
import librosa
from scipy import signal as sp_signal
from datetime import datetime
from pathlib import Path

# ================== 配置 ==================
current_dir = os.path.dirname(os.path.abspath(__file__))


def _resolve_model_path():
    env_path = os.environ.get("FISH_MODEL_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    candidates = [
        os.path.join(current_dir, "../models/fish_yamnet.tflite"),
        os.path.join(current_dir, "../model/fish_yamnet.tflite"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


MODEL_PATH = _resolve_model_path()
CHUNK_DURATION = 2.0

# ================== 滤波 ==================
def butter_lowpass_filter(data, cutoff=500, fs=22050, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    sos = sp_signal.butter(order, normal_cutoff, btype='low', output='sos')
    return sp_signal.sosfilt(sos, data)

# ================== 加载模型 ==================
def load_classifier():
    interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    class_names = ["background", "fish"]
    return interpreter, input_details, output_details, class_names

# ================== 识别片段 ==================
def classify_chunk(interpreter, input_details, output_details, audio_chunk, sr, class_names):
    try:
        audio_chunk = butter_lowpass_filter(audio_chunk, cutoff=500, fs=sr)
        mfccs = librosa.feature.mfcc(y=audio_chunk, sr=sr, n_mfcc=13, n_fft=2048, hop_length=512)
        target_length = 128
        if mfccs.shape[1] < target_length:
            mfccs = np.pad(mfccs, ((0,0), (0, target_length - mfccs.shape[1])), mode='constant')
        else:
            mfccs = mfccs[:, :target_length]

        features = mfccs.T.astype(np.float32)
        features = np.expand_dims(features, axis=0)

        interpreter.set_tensor(input_details[0]['index'], features)
        interpreter.invoke()
        output_data = interpreter.get_tensor(output_details[0]['index'])[0]
        idx = np.argmax(output_data)
        conf = float(output_data[idx])

        return {
            "predicted_class": class_names[idx],
            "confidence": round(conf, 4),
            "probabilities": {
                "background": round(float(output_data[0]), 4),
                "fish": round(float(output_data[1]), 4)
            }
        }
    except Exception as e:
        # 调试时可以打印 e，正式上线建议忽略
        return None

# ================== 合并连续片段 ==================
def merge_segments(seg_list):
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

# ================== 处理长音频 ==================
def process_audio(audio_path, interpreter, input_details, output_details, class_names):
    y, sr = librosa.load(str(audio_path), sr=22050)
    duration = len(y) / sr
    chunk_samples = int(sr * CHUNK_DURATION)
    results = []

    if len(y) < chunk_samples:
         return {
            "filename": audio_path.name,
            "total_duration": round(duration, 2),
            "total_segments": 0,
            "fish_chewing_count": 0,
            "fish_chewing_segments": [],
            "background_segments": [],
            "segments": []
        }

    for start in range(0, len(y) - chunk_samples + 1, chunk_samples):
        chunk = y[start:start+chunk_samples]
        res = classify_chunk(interpreter, input_details, output_details, chunk, sr, class_names)
        if res:
            results.append({
                "time_start": round(start / sr, 2),
                "time_end": round((start + chunk_samples) / sr, 2),
                **res
            })

    fish = [s for s in results if s["predicted_class"] == "fish"]
    bg = [s for s in results if s["predicted_class"] == "background"]

    return {
        "filename": audio_path.name,
        "total_duration": round(duration, 2),
        "total_segments": len(results),
        "fish_chewing_count": len(fish),
        "fish_chewing_segments": merge_segments(fish),
        "background_segments": merge_segments(bg),
        "segments": results
    }

# ================== 主函数 ==================
def main():
    # 恢复标准输出，确保只打印 JSON
    sys.stdout = sys.__stdout__

    if len(sys.argv) < 2:
        print(json.dumps({"error": "no file provided"}))
        return

    audio_path = Path(sys.argv[1])

    if not audio_path.exists():
        print(json.dumps({"error": f"file not found: {audio_path}"}))
        return

    if audio_path.stat().st_size < 100:
        print(json.dumps({"error": "file is empty or too small"}))
        return

    try:
        interpreter, input_details, output_details, class_names = load_classifier()
        result = process_audio(audio_path, interpreter, input_details, output_details, class_names)

        output = {
            "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": "fish_yamnet.tflite",
            "results": [result]
        }
        # 最终只打印这一行纯净的 JSON
        print(json.dumps(output, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
