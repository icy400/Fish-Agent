#!/usr/bin/env python3
"""
鱼类进食状态特征提取 - 严格按会议要求版
P值：0~200Hz 能量
C值：2秒子段鱼声概率
输出：start_time C_value P_value delta_T
"""

import numpy as np
import pandas as pd
import librosa
import tensorflow as tf
from pathlib import Path
import argparse
from scipy import signal as sp_signal

# ================== 配置区 ==================
MODEL_PATH = "models/fish_yamnet.tflite"
CHUNK_DURATION = 6.0
SUB_DURATION = 2.0

# P值频段 0 ~ 200 Hz
P_LOW_FREQ = 0
P_HIGH_FREQ = 200

# ================== 模型加载 ==================
interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
class_names = ["background", "fish"]

# ================== 滤波（模型必须） ==================
def butter_lowpass_filter(data, cutoff=500, fs=22050, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    sos = sp_signal.butter(order, normal_cutoff, btype='low', output='sos')
    return sp_signal.sosfilt(sos, data)

def predict_chunk(audio_chunk, sr):
    audio_chunk = butter_lowpass_filter(audio_chunk, 500, sr)
    mfccs = librosa.feature.mfcc(y=audio_chunk, sr=sr, n_mfcc=13, n_fft=2048, hop_length=512)
    target_length = 128
    if mfccs.shape[1] < target_length:
        mfccs = np.pad(mfccs, ((0, 0), (0, target_length - mfccs.shape[1])), mode='constant')
    else:
        mfccs = mfccs[:, :target_length]
    features = mfccs.T.astype(np.float32)[None, ...]
    interpreter.set_tensor(input_details[0]['index'], features)
    interpreter.invoke()
    output = interpreter.get_tensor(output_details[0]['index'])[0]
    return class_names[np.argmax(output)]

# ================== 主处理 ==================
def process_single_audio(audio_path, start_sec=0, duration_sec=360):
    y, sr = librosa.load(str(audio_path), sr=22050)
    y = butter_lowpass_filter(y, 500, sr)

    start_sample = int(start_sec * sr)
    end_sample = min(len(y), int((start_sec + duration_sec) * sr))
    audio_segment = y[start_sample:end_sample]

    window_samples = int(sr * CHUNK_DURATION)
    sub_samples = int(sr * SUB_DURATION)

    # 先遍历一遍，收集所有窗口 0~200Hz 能量，用于归一化
    all_energy = []
    for ws in range(0, len(audio_segment) - window_samples + 1, window_samples):
        window = audio_segment[ws:ws+window_samples]
        D = librosa.stft(window, n_fft=512, hop_length=256)
        freqs = librosa.fft_frequencies(sr=sr, n_fft=512)
        mask = (freqs >= P_LOW_FREQ) & (freqs <= P_HIGH_FREQ)
        S = np.abs(D) ** 2
        energy = np.sum(S[mask, :])
        all_energy.append(energy)

    eps = 1e-8
    min_e = np.min(all_energy) if all_energy else 0
    max_e = np.max(all_energy) if all_energy else 1

    results = []
    base_time = start_sec

    for ws in range(0, len(audio_segment) - window_samples + 1, window_samples):
        window = audio_segment[ws:ws+window_samples]
        t = base_time + ws / sr
        start_time_str = f"{int(t//60):02d}:{int(t%60):02d}"

        # 计算 C_value
        c_count = 0
        for k in range(3):
            s = k * sub_samples
            sub = window[s:s+sub_samples]
            if len(sub) < sub_samples * 0.9:
                break
            if predict_chunk(sub, sr) == "fish":
                c_count += 1
        C_value = round(c_count / 3.0, 4)

        # 计算 P_value：0~200Hz 能量，动态归一化到 0~1
        D = librosa.stft(window, n_fft=512, hop_length=256)
        freqs = librosa.fft_frequencies(sr=sr, n_fft=512)
        mask = (freqs >= P_LOW_FREQ) & (freqs <= P_HIGH_FREQ)
        S = np.abs(D) ** 2
        energy = np.sum(S[mask, :])

        if max_e - min_e < eps:
            P_value = 0.0
        else:
            P_value = (energy - min_e) / (max_e - min_e)
        P_value = round(P_value, 4)

        results.append({
            "start_time": start_time_str,
            "C_value": C_value,
            "P_value": P_value,
            "delta_T": CHUNK_DURATION
        })

    return pd.DataFrame(results)

# ================== 入口 ==================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", "-f", required=True, help="音频路径")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--duration", type=float, default=360)
    parser.add_argument("--output", "-o", default="results")
    args = parser.parse_args()

    audio_path = Path(args.file)
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)

    df = process_single_audio(audio_path, args.start, args.duration)
    out_file = output_dir / f"{audio_path.stem}_C_P.csv"
    df.to_csv(out_file, index=False, encoding='utf-8-sig')

    print("✅ 处理完成（严格 0~200Hz 计算 P）")
    print(df.head())

if __name__ == "__main__":
    main()