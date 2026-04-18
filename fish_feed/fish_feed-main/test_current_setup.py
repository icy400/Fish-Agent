#!/usr/bin/env python3
"""
Test script to verify the current AeraSync Feed setup works with installed packages.
"""

import numpy as np
import librosa
import matplotlib.pyplot as plt
import pandas as pd


def test_audio_processing():
    """Test basic audio processing capabilities."""
    print("🧪 Testing Audio Processing Capabilities")
    print("=" * 50)

    # Test 1: Generate synthetic audio signal
    print("1️⃣ Generating synthetic audio signal...")
    sample_rate = 22050
    duration = 2.0  # seconds
    frequency = 440  # Hz (A note)

    t = np.linspace(0, duration, int(sample_rate * duration))
    audio_signal = 0.5 * np.sin(2 * np.pi * frequency * t)
    print(f"   ✅ Generated {len(audio_signal)} samples at {sample_rate} Hz")

    # Test 2: Extract MFCC features
    print("2️⃣ Extracting MFCC features...")
    mfccs = librosa.feature.mfcc(y=audio_signal, sr=sample_rate, n_mfcc=13)
    print(f"   ✅ MFCC shape: {mfccs.shape}")

    # Test 3: Create spectrogram
    print("3️⃣ Creating spectrogram...")
    stft = librosa.stft(audio_signal)
    spectrogram = np.abs(stft)
    print(f"   ✅ Spectrogram shape: {spectrogram.shape}")

    # Test 4: Save visualization
    print("4️⃣ Creating visualization...")
    plt.figure(figsize=(12, 6))

    plt.subplot(2, 2, 1)
    plt.plot(t[:1000], audio_signal[:1000])
    plt.title("Audio Waveform (first 1000 samples)")
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude")

    plt.subplot(2, 2, 2)
    librosa.display.specshow(
        librosa.amplitude_to_db(spectrogram),
        sr=sample_rate,
        x_axis="time",
        y_axis="hz",
    )
    plt.title("Spectrogram")
    plt.colorbar()

    plt.subplot(2, 2, 3)
    librosa.display.specshow(mfccs, sr=sample_rate, x_axis="time")
    plt.title("MFCC Features")
    plt.colorbar()

    plt.subplot(2, 2, 4)
    # Feature statistics
    feature_stats = {
        "Mean MFCC": np.mean(mfccs, axis=1),
        "Std MFCC": np.std(mfccs, axis=1),
    }
    df = pd.DataFrame(feature_stats)
    print("   📊 MFCC Statistics:")
    print(df.head())

    plt.plot(df["Mean MFCC"], label="Mean MFCC")
    plt.plot(df["Std MFCC"], label="Std MFCC")
    plt.title("MFCC Statistics")
    plt.legend()

    plt.tight_layout()
    plt.savefig("test_audio_processing.png", dpi=100, bbox_inches="tight")
    print("✅ Visualization saved to: test_audio_processing.png")

    # Test 5: Data handling
    print("5️⃣ Testing data handling...")
    test_data = {
        "filename": ["test1.wav", "test2.wav", "test3.wav"],
        "label": ["fish_chewing", "aerator_noise", "background"],
        "duration": [2.5, 3.0, 1.8],
        "sample_rate": [22050, 22050, 22050],
    }
    df = pd.DataFrame(test_data)
    df.to_csv("test_labels.csv", index=False)
    print("✅ Test labels saved to: test_labels.csv")
    print(df)

    print(
        "\n🎉 All tests passed! Your environment is ready for audio processing."
    )
    return True


def show_next_steps():
    """Show what the user can do next."""
    print("\n🚀 What You Can Do Next:")
    print()
    print("📁 Data Collection:")
    print("   • Record or collect audio samples of shrimp chewing")
    print("   • Record aerator noise samples")
    print("   • Record background aquaculture sounds")
    print("   • Place files in data/audio/[class_name]/ directories")
    print()
    print("🔄 Processing Pipeline:")
    print("   • Use scripts/preprocess.py to extract features")
    print("   • Analyze your audio data with the current tools")
    print("   • Develop feeding detection logic")
    print()
    print("☁️ Training Options:")
    print("   • Use Google Colab for TensorFlow model training")
    print("   • Export trained models for local inference")
    print("   • Convert models to TensorFlow Lite for Raspberry Pi")
    print()
    print("🥧 Deployment:")
    print("   • Test inference scripts with dummy models")
    print("   • Prepare Raspberry Pi deployment scripts")


if __name__ == "__main__":
    try:
        test_audio_processing()
        show_next_steps()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        print("Please check your environment setup.")
