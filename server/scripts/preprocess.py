#!/usr/bin/env python3
"""
Audio preprocessing script for AeraSync Feed project.
Converts audio files into spectrograms or MFCCs for model training.
"""

import os
import argparse
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from pathlib import Path
import json
import logging

from audio_features import LOWPASS_CUTOFF, LOWPASS_ORDER, butter_lowpass_filter

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加入 500Hz 低通滤波的版本
def extract_features(
        audio_file, sr=22050, n_mfcc=13, n_fft=2048, hop_length=512
):
    """
    提取特征前先进行 500Hz 低通滤波，然后提取 MFCC 和 Spectrogram
    """
    try:
        # Load audio file
        y, sr = librosa.load(audio_file, sr=sr)

        y = butter_lowpass_filter(y, cutoff=LOWPASS_CUTOFF, fs=sr, order=LOWPASS_ORDER)

        # Extract MFCCs
        mfccs = librosa.feature.mfcc(
            y=y, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length
        )

        # Extract mel spectrogram（这是你想要的主要特征）
        mel_spec = librosa.feature.melspectrogram(
            y=y, sr=sr, n_fft=n_fft, hop_length=hop_length
        )
        mel_spec_db = librosa.power_to_db(mel_spec, ref=np.max)

        # Extract spectral features
        spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
        zero_crossing_rate = librosa.feature.zero_crossing_rate(y)[0]

        return {
            "mfccs": mfccs,
            "mel_spectrogram": mel_spec_db,  # ← 你主要想用的特征
            "spectral_centroids": spectral_centroids,
            "spectral_rolloff": spectral_rolloff,
            "zero_crossing_rate": zero_crossing_rate,
            "sample_rate": sr,
            "duration": len(y) / sr,
        }

    except Exception as e:
        logger.error(f"Error processing {audio_file}: {str(e)}")
        return None

# def extract_features(
#     audio_file, sr=22050, n_mfcc=13, n_fft=2048, hop_length=512
# ):
#     """
#     Extract audio features (MFCCs and spectrograms) from audio file.
#
#     Args:
#         audio_file (str): Path to audio file
#         sr (int): Sample rate
#         n_mfcc (int): Number of MFCC coefficients
#         n_fft (int): FFT window size
#         hop_length (int): Hop length for STFT
#
#     Returns:
#         dict: Dictionary containing extracted features
#     """
#     try:
#         # Load audio file
#         y, sr = librosa.load(audio_file, sr=sr)
#
#         # Extract MFCCs
#         mfccs = librosa.feature.mfcc(
#             y=y, sr=sr, n_mfcc=n_mfcc, n_fft=n_fft, hop_length=hop_length
#         )
#
#         # Extract mel spectrogram
#         mel_spec = librosa.feature.melspectrogram(
#             y=y, sr=sr, n_fft=n_fft, hop_length=hop_length
#         )
#         mel_spec_db = librosa.power_to_db(mel_spec, ref=np.max)
#
#         # Extract spectral features
#         spectral_centroids = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
#         spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
#         zero_crossing_rate = librosa.feature.zero_crossing_rate(y)[0]
#
#         return {
#             "mfccs": mfccs,
#             "mel_spectrogram": mel_spec_db,
#             "spectral_centroids": spectral_centroids,
#             "spectral_rolloff": spectral_rolloff,
#             "zero_crossing_rate": zero_crossing_rate,
#             "sample_rate": sr,
#             "duration": len(y) / sr,
#         }
#
#     except Exception as e:
#         logger.error(f"Error processing {audio_file}: {str(e)}")
#         return None




def save_spectrogram_image(spectrogram, output_path, title="Spectrogram"):
    """
    Save spectrogram as image file.

    Args:
        spectrogram (np.array): Spectrogram data
        output_path (str): Output file path
        title (str): Plot title
    """
    plt.figure(figsize=(10, 6))
    librosa.display.specshow(spectrogram, x_axis="time", y_axis="mel")
    plt.colorbar(format="%+2.0f dB")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

def process_audio_files(input_dir, output_dir, save_images=False):
    """
    Process all audio files in input directory.

    Args:
        input_dir (str): Input directory containing audio files
        output_dir (str): Output directory for processed features
        save_images (bool): Whether to save spectrogram images
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    features_dir = output_path / "features"
    features_dir.mkdir(exist_ok=True)

    if save_images:
        images_dir = output_path / "images"
        images_dir.mkdir(exist_ok=True)

    # Supported audio formats
    audio_extensions = [".wav", ".mp3", ".flac", ".m4a", ".ogg"]

    processed_files = []

    for audio_file in input_path.rglob("*"):
        if audio_file.suffix.lower() in audio_extensions:
            logger.info(f"Processing: {audio_file}")

            # Extract features
            features = extract_features(str(audio_file))

            if features is not None:
                # Save features as numpy file
                feature_filename = audio_file.stem + "_features.npz"
                feature_path = features_dir / feature_filename

                np.savez_compressed(str(feature_path), **features)

                # Save spectrogram image if requested
                if save_images:
                    img_filename = audio_file.stem + "_spectrogram.png"
                    img_path = images_dir / img_filename
                    save_spectrogram_image(
                        features["mel_spectrogram"],
                        str(img_path),
                        f"Mel Spectrogram - {audio_file.stem}",
                    )

                processed_files.append(
                    {
                        "original_file": str(audio_file),
                        "features_file": str(feature_path),
                        "duration": features["duration"],
                        "sample_rate": features["sample_rate"],
                    }
                )

    # Save processing summary
    summary_path = output_path / "processing_summary.json"
    with open(summary_path, "w") as f:
        json.dump(processed_files, f, indent=2)

    logger.info(f"Processed {len(processed_files)} audio files")
    logger.info(f"Features saved to: {features_dir}")
    logger.info(f"Summary saved to: {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Preprocess audio files for AeraSync Feed"
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Input directory containing audio files",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for processed features",
    )
    parser.add_argument(
        "--save-images", action="store_true", help="Save spectrogram images"
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=22050,
        help="Target sample rate (default: 22050)",
    )
    parser.add_argument(
        "--n-mfcc",
        type=int,
        default=13,
        help="Number of MFCC coefficients (default: 13)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        logger.error(f"Input directory does not exist: {args.input}")
        return

    logger.info("Starting audio preprocessing...")
    process_audio_files(args.input, args.output, args.save_images)
    logger.info("Preprocessing completed!")


if __name__ == "__main__":
    main()
