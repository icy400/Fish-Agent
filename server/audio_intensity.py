"""Low-frequency audio intensity helpers for realtime fish-sound chunks."""

import math
import wave
from pathlib import Path


LOW_FREQ_HZ = 0
HIGH_FREQ_HZ = 200
LOWPASS_CUTOFF_HZ = 500
LOWPASS_ORDER = 4
N_FFT = 512
HOP_LENGTH = 256


def calculate_sound_intensity(audio_path):
    samples, sample_rate = load_wav_samples(audio_path)
    return calculate_band_intensity(samples, sample_rate=sample_rate)


def load_wav_samples(audio_path):
    with wave.open(str(Path(audio_path)), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise ValueError("only 16-bit PCM WAV realtime chunks are supported for intensity")

    values = []
    frame_count = len(frames) // sample_width
    for i in range(frame_count):
        raw = frames[i * sample_width : (i + 1) * sample_width]
        value = int.from_bytes(raw, byteorder="little", signed=True) / 32768.0
        values.append(value)

    if channels <= 1:
        return values, sample_rate

    mono = []
    for i in range(0, len(values), channels):
        frame = values[i : i + channels]
        if frame:
            mono.append(sum(frame) / len(frame))
    return mono, sample_rate


def calculate_band_intensity(samples, sample_rate, low_hz=LOW_FREQ_HZ, high_hz=HIGH_FREQ_HZ):
    samples = [float(value) for value in samples]
    if not samples:
        return 0.0
    if not any(samples):
        return 0.0

    filtered = _maybe_butter_lowpass(samples, sample_rate)
    if len(filtered) < N_FFT:
        filtered = filtered + [0.0] * (N_FFT - len(filtered))

    bins = _frequency_bins(sample_rate, low_hz, high_hz)
    if not bins:
        return 0.0

    window = _hann_window(N_FFT)
    total_power = 0.0
    count = 0
    for start in range(0, len(filtered) - N_FFT + 1, HOP_LENGTH):
        frame = filtered[start : start + N_FFT]
        for bin_index in bins:
            real = 0.0
            imag = 0.0
            for n, sample in enumerate(frame):
                angle = 2.0 * math.pi * bin_index * n / N_FFT
                weighted = sample * window[n]
                real += weighted * math.cos(angle)
                imag -= weighted * math.sin(angle)
            total_power += (real * real + imag * imag) / N_FFT
            count += 1

    if count == 0:
        return 0.0
    return round(total_power / count, 6)


def _frequency_bins(sample_rate, low_hz, high_hz):
    max_bin = N_FFT // 2
    bins = []
    for bin_index in range(max_bin + 1):
        freq = bin_index * sample_rate / N_FFT
        if low_hz <= freq <= high_hz:
            bins.append(bin_index)
    return bins


def _hann_window(length):
    if length <= 1:
        return [1.0]
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * n / (length - 1)) for n in range(length)]


def _maybe_butter_lowpass(samples, sample_rate):
    try:
        import numpy as np
        from scipy import signal as sp_signal
    except Exception:
        return samples

    nyq = 0.5 * sample_rate
    normal_cutoff = LOWPASS_CUTOFF_HZ / nyq
    sos = sp_signal.butter(LOWPASS_ORDER, normal_cutoff, btype="low", output="sos")
    return sp_signal.sosfilt(sos, np.asarray(samples, dtype=float)).tolist()
