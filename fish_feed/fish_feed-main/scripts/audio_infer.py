"""
长音频 单文件测试脚本 - JSON 格式完全不变
输出文件名：audio_infer_result_原音频名.json
"""

import json
from datetime import datetime
import numpy as np
import tensorflow as tf
import librosa
from scipy import signal as sp_signal
import argparse
from pathlib import Path

# ================== 配置区 ==================
MODEL_PATH = "models/fish_yamnet.tflite"
LABELS_PATH = "models/fish_yamnet/label_encoder.json"

CHUNK_DURATION = 2.0
OVERLAP = 0.0

# ================== 低通滤波函数 ==================
def butter_lowpass_filter(data, cutoff=500, fs=22050, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    sos = sp_signal.butter(order, normal_cutoff, btype='low', output='sos')
    y = sp_signal.sosfilt(sos, data)
    return y

def load_classifier():
    interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    with open(LABELS_PATH, "r", encoding="utf-8") as f:
        label_data = json.load(f)
        class_names = label_data.get("classes", ["background", "fish"])

    print(f"模型加载完成，类别: {class_names}\n")
    return interpreter, input_details, output_details, class_names

def classify_chunk(interpreter, input_details, output_details, audio_chunk, sr, class_names):
    try:
        audio_chunk = butter_lowpass_filter(audio_chunk, cutoff=500, fs=sr)
        mfccs = librosa.feature.mfcc(y=audio_chunk, sr=sr, n_mfcc=13, n_fft=2048, hop_length=512)
        target_length = 128
        if mfccs.shape[1] < target_length:
            mfccs = np.pad(mfccs, ((0, 0), (0, target_length - mfccs.shape[1])), mode="constant")
        else:
            mfccs = mfccs[:, :target_length]

        features = mfccs.T.astype(np.float32)
        features = np.expand_dims(features, axis=0)

        interpreter.set_tensor(input_details[0]['index'], features)
        interpreter.invoke()
        output_data = interpreter.get_tensor(output_details[0]['index'])[0]
        predicted_idx = np.argmax(output_data)
        confidence = float(output_data[predicted_idx])

        return {
            "predicted_class": class_names[predicted_idx],
            "confidence": round(confidence, 4),
            "probabilities": {class_names[i]: round(float(output_data[i]), 4) for i in range(len(class_names))}
        }
    except Exception as e:
        print(f"分段分类错误: {e}")
        return None

def merge_continuous_segments(segments):
    if not segments:
        return []
    merged = []
    current = {"time_start": segments[0]["time_start"], "time_end": segments[0]["time_end"]}
    for seg in segments[1:]:
        if abs(seg["time_start"] - current["time_end"]) <= 0.1:
            current["time_end"] = seg["time_end"]
        else:
            merged.append(current)
            current = {"time_start": seg["time_start"], "time_end": seg["time_end"]}
    merged.append(current)
    return merged

def process_long_audio(audio_path, interpreter, input_details, output_details, class_names):
    try:
        y, sr = librosa.load(str(audio_path), sr=22050)
        duration = len(y) / sr
        print(f"处理: {audio_path.name} | 时长: {duration:.2f} 秒")

        results = []
        chunk_samples = int(sr * CHUNK_DURATION)

        for start in range(0, len(y) - chunk_samples + 1, chunk_samples):
            chunk = y[start:start + chunk_samples]
            segment_result = classify_chunk(interpreter, input_details, output_details, chunk, sr, class_names)
            if segment_result:
                time_start = round(start / sr, 2)
                time_end = round(time_start + CHUNK_DURATION, 2)
                segment = {
                    "time_start": time_start,
                    "time_end": time_end,
                    **segment_result
                }
                results.append(segment)

        fish_segments = [seg for seg in results if seg["predicted_class"] == "fish"]
        bg_segments = [seg for seg in results if seg["predicted_class"] == "background"]

        fish_merged = merge_continuous_segments(fish_segments)
        bg_merged = merge_continuous_segments(bg_segments)

        return {
            "filename": audio_path.name,
            "total_duration": round(duration, 2),
            "total_segments": len(results),
            "fish_chewing_count": len(fish_segments),
            "fish_chewing_segments": fish_merged,
            "background_segments": bg_merged,
            "segments": results
        }
    except Exception as e:
        print(f"处理失败: {e}")
        return None

# ================== 主函数 ==================
def main():
    parser = argparse.ArgumentParser(description="长音频单文件测试")
    parser.add_argument("--file", "-f", required=True, help="要测试的音频文件路径")
    args = parser.parse_args()

    audio_path = Path(args.file)
    if not audio_path.exists():
        print("❌ 文件不存在")
        return

    interpreter, input_details, output_details, class_names = load_classifier()
    file_result = process_long_audio(audio_path, interpreter, input_details, output_details, class_names)

    # 输出目录
    output_dir = Path("test_results/audio_infer_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 文件名：audio_infer_result_原音频名.json
    stem = audio_path.stem  # 去掉后缀的文件名
    result_file = output_dir / f"audio_infer_result_{stem}.json"

    final_output = {
        "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": MODEL_PATH,
        "results": [file_result]
    }

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 处理完成！")
    print(f"结果已保存到: {result_file}")

if __name__ == "__main__":
    main()