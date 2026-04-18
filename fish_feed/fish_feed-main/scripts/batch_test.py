"""
批量测试脚本 - 测试 fish_chewing 和 background 两个文件夹
加入 500Hz 低通滤波（与训练/推理完全一致）
生成统一的 JSON 结果文件，并计算各自正确率
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import tensorflow as tf
import librosa
from scipy import signal  # 滤波需要

# ================== 配置区 ==================
MODEL_PATH = "models/fish_yamnet.tflite"
LABELS_PATH = "models/fish_yamnet/label_encoder.json"

TEST_FISH_DIR = r"data/test/fish_chewing"
TEST_BACKGROUND_DIR = r"data/test/background"

OUTPUT_DIR = "test_results/batch_test"
SUPPORTED_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}

# ================== 滤波函数（必须加！） ==================
def butter_lowpass_filter(data, cutoff=500, fs=22050, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    sos = signal.butter(order, normal_cutoff, btype='low', output='sos')
    y = signal.sosfilt(sos, data)
    return y

def load_model_and_labels():
    interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    with open(LABELS_PATH, "r", encoding="utf-8") as f:
        label_data = json.load(f)
        class_names = label_data.get("classes", ["background", "fish"])

    print(f"模型加载完成，类别: {class_names}\n")
    return interpreter, input_details, output_details, class_names


def predict_audio(interpreter, input_details, output_details, audio_path, class_names):
    try:
        y, sr = librosa.load(str(audio_path), sr=22050)

        # ================== 500Hz 低通滤波 ==================
        y = butter_lowpass_filter(y, cutoff=500, fs=sr)

        # 提取 MFCC 特征（与训练一致）
        mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, n_fft=2048, hop_length=512)
        target_length = 128
        if mfccs.shape[1] < target_length:
            mfccs = np.pad(mfccs, ((0, 0), (0, target_length - mfccs.shape[1])), mode="constant")
        else:
            mfccs = mfccs[:, :target_length]

        features = mfccs.T.astype(np.float32)
        features = np.expand_dims(features, axis=0)

        start_time = time.time()
        interpreter.set_tensor(input_details[0]['index'], features)
        interpreter.invoke()
        inference_time = time.time() - start_time

        output_data = interpreter.get_tensor(output_details[0]['index'])[0]
        predicted_idx = np.argmax(output_data)
        confidence = float(output_data[predicted_idx])
        predicted_class = class_names[predicted_idx]

        return {
            "filename": audio_path.name,
            "predicted_class": predicted_class,
            "confidence": round(confidence, 4),
            "inference_time": round(inference_time, 4),
            "probabilities": {class_names[i]: round(float(output_data[i]), 4) for i in range(len(class_names))}
        }

    except Exception as e:
        return {
            "filename": audio_path.name,
            "error": str(e)
        }


def batch_test():
    interpreter, input_details, output_details, class_names = load_model_and_labels()

    all_results = []
    fish_correct = 0
    fish_total = 0
    bg_correct = 0
    bg_total = 0

    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("正在测试 fish_chewing 文件夹...")
    fish_path = Path(TEST_FISH_DIR)
    if fish_path.exists():
        for audio_file in fish_path.rglob("*"):
            if audio_file.suffix.lower() in SUPPORTED_EXT:
                fish_total += 1
                result = predict_audio(interpreter, input_details, output_details, audio_file, class_names)
                all_results.append({"folder": "fish_chewing", **result})

                if result.get("predicted_class") == "fish":
                    fish_correct += 1

                print(f"fish_chewing/{audio_file.name} → {result.get('predicted_class')} ({result.get('confidence', 0):.4f})")

    print("\n正在测试 background 文件夹...")
    bg_path = Path(TEST_BACKGROUND_DIR)
    if bg_path.exists():
        for audio_file in bg_path.rglob("*"):
            if audio_file.suffix.lower() in SUPPORTED_EXT:
                bg_total += 1
                result = predict_audio(interpreter, input_details, output_details, audio_file, class_names)
                all_results.append({"folder": "background", **result})

                if result.get("predicted_class") == "background":
                    bg_correct += 1

                print(f"background/{audio_file.name} → {result.get('predicted_class')} ({result.get('confidence', 0):.4f})")

    fish_acc = round(fish_correct / fish_total * 100, 2) if fish_total > 0 else 0
    bg_acc = round(bg_correct / bg_total * 100, 2) if bg_total > 0 else 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"batch_test_results_{timestamp}.json"
    output_path = output_dir / output_filename

    output_data = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": MODEL_PATH,
        "total_files": len(all_results),
        "fish_chewing": {"total": fish_total, "correct": fish_correct, "accuracy": fish_acc},
        "background": {"total": bg_total, "correct": bg_correct, "accuracy": bg_acc},
        "results": all_results
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print("\n" + "="*70)
    print("测试完成！")
    print(f"fish_chewing 正确率: {fish_acc}%  ({fish_correct}/{fish_total})")
    print(f"background 正确率: {bg_acc}%   ({bg_correct}/{bg_total})")
    print(f"总测试文件: {len(all_results)} 个")
    print(f"详细结果已保存到: {output_path}")

if __name__ == "__main__":
    batch_test()