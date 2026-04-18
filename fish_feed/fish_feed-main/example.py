#!/usr/bin/env python3
"""
Example usage script for AeraSync Feed project.
Demonstrates the complete workflow from data preprocessing to inference.
"""

import sys
import os
import json
from pathlib import Path

# Add scripts directory to path
sys.path.append(str(Path(__file__).parent / "scripts"))


def example_workflow():
    """Example workflow demonstrating the AeraSync Feed pipeline."""

    print("🦐 AeraSync Feed - Example Workflow")
    print("=" * 50)

    # Step 1: Data preprocessing
    print("\n1️⃣ Data Preprocessing")
    print("   Converts raw audio files to MFCC features")
    print(
        "   Command: python scripts/preprocess.py --input data/audio --output data/processed"
    )
    print("   Options:")
    print("     --save-images    Save spectrogram images")
    print("     --sample-rate    Target sample rate (default: 22050)")
    print("     --n-mfcc         Number of MFCC coefficients (default: 13)")

    # Step 2: Model training
    print("\n2️⃣ Model Training")
    print("   Fine-tunes a model for audio classification")
    print(
        "   Command: python scripts/train.py --data data/processed --output models/yamnet_finetuned"
    )
    print("   Options:")
    print("     --labels         Path to labels file (CSV or JSON)")
    print("     --epochs         Number of training epochs (default: 50)")
    print("     --batch-size     Training batch size (default: 32)")

    # Step 3: Model conversion
    print("\n3️⃣ Model Conversion")
    print("   Converts trained model to TensorFlow Lite for deployment")
    print(
        "   Command: python scripts/convert_tflite.py --model models/yamnet_finetuned/final_model.h5 --output models/yamnet.tflite"
    )
    print("   Options:")
    print("     --data           Data directory for quantization")
    print("     --no-quantize    Disable quantization optimization")
    print("     --test           Test the converted model")

    # Step 4: Inference
    print("\n4️⃣ Inference")
    print("   Runs real-time audio classification")
    print(
        "   Command: python scripts/infer.py --model models/yamnet.tflite --labels models/yamnet_finetuned/label_encoder.json"
    )
    print("   Options:")
    print("     --file           Classify single audio file")
    print("     --device         Audio device index for recording")
    print("     --duration       Audio chunk duration (default: 2.0s)")
    print("     --overlap        Overlap between chunks (default: 0.5)")

    # Example file classification
    print("\n📁 File Classification Example:")
    print("   python scripts/infer.py \\")
    print("     --model models/yamnet.tflite \\")
    print("     --labels models/yamnet_finetuned/label_encoder.json \\")
    print("     --file data/audio/fish_chewing/sample.wav")

    # Example real-time classification
    print("\n🎤 Real-time Classification Example:")
    print("   python scripts/infer.py \\")
    print("     --model models/yamnet.tflite \\")
    print("     --labels models/yamnet_finetuned/label_encoder.json \\")
    print("     --device 0 \\")
    print("     --duration 2.0")


def create_sample_config():
    """Create a sample configuration file."""
    config = {
        "audio_settings": {
            "sample_rate": 22050,
            "chunk_duration": 2.0,
            "overlap": 0.5,
            "n_mfcc": 13,
        },
        "training_settings": {
            "epochs": 50,
            "batch_size": 32,
            "validation_split": 0.2,
            "early_stopping_patience": 10,
        },
        "model_settings": {
            "use_yamnet": True,
            "quantize_model": True,
            "target_accuracy": 0.85,
        },
        "classes": ["fish_chewing", "aerator_noise", "background"],
        "feeding_logic": {
            "shrimp_threshold": 0.7,
            "aerator_threshold": 0.8,
            "confidence_window": 5,
        },
    }

    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n📝 Sample configuration saved to: {config_path}")
    return config_path


def show_project_structure():
    """Show the expected project structure."""
    print("\n📂 Project Structure:")
    print("""
aerasync_feed/
├── data/
│   ├── audio/
│   │   ├── fish_chewing/     # Shrimp chewing audio files
│   │   ├── aerator_noise/      # Aerator noise audio files
│   │   └── background/         # Background audio files
│   ├── processed/              # Preprocessed features
│   └── labels.csv              # Audio file labels
├── models/
│   ├── yamnet_finetuned/       # Trained model directory
│   └── yamnet.tflite           # TensorFlow Lite model
├── scripts/
│   ├── preprocess.py           # Audio preprocessing
│   ├── train.py                # Model training
│   ├── convert_tflite.py       # Model conversion
│   └── infer.py                # Real-time inference
├── config.json                 # Configuration file
├── requirements.txt            # Python dependencies
├── setup.py                    # Setup script
└── README.md                   # Documentation
    """)


def show_raspberry_pi_setup():
    """Show Raspberry Pi setup instructions."""
    print("\n🥧 Raspberry Pi Setup:")
    print("1. Install system dependencies:")
    print("   sudo apt-get update")
    print("   sudo apt-get install python3-pip portaudio19-dev python3-dev")
    print("")
    print("2. Install Python packages:")
    print("   pip3 install tensorflow-lite numpy librosa pyaudio")
    print("")
    print("3. Copy model files to Raspberry Pi:")
    print("   scp models/yamnet.tflite pi@raspberry-pi:~/")
    print(
        "   scp models/yamnet_finetuned/label_encoder.json pi@raspberry-pi:~/"
    )
    print("")
    print("4. Run inference on Raspberry Pi:")
    print(
        "   python3 infer.py --model yamnet.tflite --labels label_encoder.json"
    )
    print("")
    print("5. For GPIO integration:")
    print("   pip3 install RPi.GPIO")
    print(
        "   # Add GPIO control code to feeding_decision_callback in infer.py"
    )


def main():
    """Main example function."""

    if len(sys.argv) > 1:
        command = sys.argv[1].lower()

        if command == "workflow":
            example_workflow()
        elif command == "structure":
            show_project_structure()
        elif command == "config":
            create_sample_config()
        elif command == "raspberry-pi":
            show_raspberry_pi_setup()
        else:
            print(f"Unknown command: {command}")
            print(
                "Available commands: workflow, structure, config, raspberry-pi"
            )
    else:
        # Show all information
        example_workflow()
        show_project_structure()
        create_sample_config()
        show_raspberry_pi_setup()

        print("\n🚀 Quick Start:")
        print("1. Run setup: python setup.py")
        print("2. Add audio files to data/audio/ directories")
        print("3. Follow the workflow above")
        print("4. Deploy to Raspberry Pi")


if __name__ == "__main__":
    main()
