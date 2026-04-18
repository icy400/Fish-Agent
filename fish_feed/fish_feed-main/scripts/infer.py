"""
Real-time inference script for AeraSync Feed project.
Runs audio classification on Raspberry Pi using TensorFlow Lite model.
"""

import os
import argparse
import numpy as np
import tensorflow as tf
import librosa
import json
import time
import logging
from pathlib import Path
import threading
import queue
import signal           # ✅ 系统信号（单独导入）
import sys

# ✅ 滤波改名导入，避免冲突！
from scipy import signal as sp_signal

# For audio recording (you may need to install pyaudio: pip install pyaudio)
try:
    import pyaudio

    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logging.warning("PyAudio not available. Audio recording will be disabled.")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AudioClassifier:
    """Real-time audio classifier using TensorFlow Lite."""

    def __init__(
        self,
        model_path,
        label_encoder_path=None,
        sample_rate=22050,
        chunk_duration=2.0,
        overlap=0.5,
    ):
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.overlap = overlap

        self.chunk_samples = int(sample_rate * chunk_duration)
        self.hop_samples = int(self.chunk_samples * (1 - overlap))

        self.interpreter = tf.lite.Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()

        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        self.input_shape = self.input_details[0]["shape"]
        self.output_shape = self.output_details[0]["shape"]

        logger.info(f"Model loaded: {model_path}")
        logger.info(f"Input shape: {self.input_shape}")

        self.class_names = None
        if label_encoder_path and os.path.exists(label_encoder_path):
            with open(label_encoder_path, "r") as f:
                label_data = json.load(f)
                self.class_names = label_data.get("classes", None)
            logger.info(f"Loaded {len(self.class_names)} classes: {self.class_names}")

        self.audio_buffer = np.array([])
        self.is_running = False

    # ================== 500Hz 低通滤波 ==================
    def butter_lowpass_filter(self, data, cutoff=500, fs=22050, order=4):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        sos = sp_signal.butter(order, normal_cutoff, btype='low', output='sos')
        y = sp_signal.sosfilt(sos, data)
        return y

    def extract_features(self, audio_data):
        try:
            #  滤波
            audio_data = self.butter_lowpass_filter(audio_data, cutoff=500, fs=self.sample_rate)

            mfccs = librosa.feature.mfcc(
                y=audio_data,
                sr=self.sample_rate,
                n_mfcc=13,
                n_fft=2048,
                hop_length=512,
            )

            target_length = 128
            if mfccs.shape[1] < target_length:
                mfccs = np.pad(
                    mfccs,
                    ((0, 0), (0, target_length - mfccs.shape[1])),
                    mode="constant",
                )
            else:
                mfccs = mfccs[:, :target_length]

            features = mfccs.T
            features = np.expand_dims(features, axis=0).astype(np.float32)

            return features

        except Exception as e:
            logger.error(f"Feature extraction error: {str(e)}")
            return None

    def classify_audio(self, audio_data):
        features = self.extract_features(audio_data)
        if features is None:
            return None

        if features.shape != tuple(self.input_shape):
            logger.warning(f"Feature shape {features.shape}")
            return None

        try:
            self.interpreter.set_tensor(self.input_details[0]["index"], features)
            self.interpreter.invoke()
            output_data = self.interpreter.get_tensor(self.output_details[0]["index"])
            predictions = output_data[0]

            predicted_class_idx = np.argmax(predictions)
            confidence = predictions[predicted_class_idx]

            predicted_class = (
                self.class_names[predicted_class_idx]
                if self.class_names
                else f"Class_{predicted_class_idx}"
            )

            return {
                "predicted_class": predicted_class,
                "confidence": float(confidence),
                "probabilities": predictions.tolist(),
                "inference_time": 0,
            }

        except Exception as e:
            logger.error(f"Classification error: {str(e)}")
            return None

    def classify_file(self, audio_file):
        try:
            audio_data, sr = librosa.load(audio_file, sr=self.sample_rate)
            return self.classify_audio(audio_data)
        except Exception as e:
            logger.error(f"Error processing file {audio_file}: {str(e)}")
            return None

    def start_realtime_classification(
        self, device_index=None, decision_callback=None
    ):
        if not PYAUDIO_AVAILABLE:
            logger.error("PyAudio not available.")
            return

        self.is_running = True
        audio = pyaudio.PyAudio()

        try:
            stream = audio.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=1024,
            )

            logger.info("Starting real-time audio classification...")

            while self.is_running:
                data = stream.read(1024, exception_on_overflow=False)
                audio_chunk = np.frombuffer(data, dtype=np.float32)
                self.audio_buffer = np.append(self.audio_buffer, audio_chunk)

                if len(self.audio_buffer) >= self.chunk_samples:
                    chunk = self.audio_buffer[: self.chunk_samples]
                    result = self.classify_audio(chunk)

                    if result:
                        logger.info(f"Real-time prediction: {result['predicted_class']} ({result['confidence']:.3f})")
                        if decision_callback:
                            decision_callback(result)

                    self.audio_buffer = self.audio_buffer[self.hop_samples :]

        finally:
            stream.stop_stream()
            stream.close()
            audio.terminate()
            logger.info("Stopped")


def feeding_decision_callback(result):
    predicted_class = result["predicted_class"]
    confidence = result["confidence"]

    if predicted_class == "fish" and confidence > 0.5:
        logger.info("✅ 检测到鱼吃食")
    else:
        logger.info(f"🔇 {predicted_class}")


def signal_handler(sig, frame):
    logger.info("Stopping...")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Real-time audio classification")
    parser.add_argument("--model", "-m", required=True, help="Path to TFLite model")
    parser.add_argument("--labels", "-l", help="Path to label encoder JSON")
    parser.add_argument("--file", "-f", help="Audio file to classify")
    args = parser.parse_args()

    classifier = AudioClassifier(
        model_path=args.model,
        label_encoder_path=args.labels,
    )

    signal.signal(signal.SIGINT, signal_handler)

    if args.file:
        result = classifier.classify_file(args.file)
        if result:
            print(f"\nResult: {result['predicted_class']} | conf: {result['confidence']:.3f}")
    else:
        classifier.start_realtime_classification(decision_callback=feeding_decision_callback)


if __name__ == "__main__":
    main()
