#!/usr/bin/env python3
"""
Setup script for AeraSync Feed project.
Helps users set up the development environment and check dependencies.

Note: This script uses dynamic imports (__import__) in some places to handle
optional dependencies gracefully. This is intentional to avoid import errors
when packages are not installed, which is the purpose of this setup script.
"""

import sys
import subprocess
import platform
from pathlib import Path


def check_python_version():
    """Check if Python version is compatible."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ Python 3.8+ is required")
        print(
            f"   Current version: {version.major}.{version.minor}.{version.micro}"
        )
        return False
    else:
        print(
            f"✅ Python version: {version.major}.{version.minor}.{version.micro}"
        )
        return True


def check_system_dependencies():
    """Check system-level dependencies."""
    print("\n🔍 Checking system dependencies...")

    dependencies = {
        "git": "git --version",
        "python3": "python3 --version",
        "pip": "pip --version",
    }

    missing = []
    for dep, cmd in dependencies.items():
        try:
            subprocess.run(cmd.split(), check=True, capture_output=True)
            print(f"✅ {dep} is installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"❌ {dep} is not installed or not in PATH")
            missing.append(dep)

    return len(missing) == 0


def check_audio_dependencies():
    """Check audio-related system dependencies."""
    print("\n🔊 Checking audio dependencies...")

    system = platform.system().lower()

    if system == "linux":
        print(
            "   On Ubuntu/Debian, install: sudo apt-get install portaudio19-dev python3-dev"
        )
        print(
            "   On CentOS/RHEL, install: sudo yum install portaudio-devel python3-devel"
        )
    elif system == "darwin":  # macOS
        print("   On macOS, install: brew install portaudio")
    elif system == "windows":
        print("   On Windows, PyAudio should install automatically with pip")

    return True


def install_requirements():
    """Install Python requirements with flexible options."""
    print("\n📦 Installing Python requirements...")

    base_dir = Path(__file__).parent

    # Try installing requirements in order of preference
    requirements_files = [
        ("requirements-base.txt", "base dependencies"),
        ("requirements-tensorflow.txt", "TensorFlow (for training)"),
        ("requirements-audio.txt", "audio recording support"),
    ]

    success = True

    for req_file, description in requirements_files:
        req_path = base_dir / req_file
        if req_path.exists():
            print(f"\n   Installing {description}...")
            try:
                cmd = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(req_path),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                print(f"   ✅ {description} installed successfully")
            except subprocess.CalledProcessError as e:
                print(f"   ⚠️  Failed to install {description}")
                if req_file == "requirements-tensorflow.txt":
                    print("   ℹ️  TensorFlow installation failed. You can:")
                    print("      - Use Google Colab for training")
                    print("      - Install TensorFlow manually later")
                    print("      - Use TensorFlow Lite for inference only")
                elif req_file == "requirements-audio.txt":
                    print("   ℹ️  Audio recording support failed. You can:")
                    print("      - Install system audio dependencies first")
                    print("      - Use file-based inference instead")
                else:
                    success = False
                    print(f"   ❌ Critical dependency failure: {e}")

    return success


def check_installed_packages():
    """Check if required packages are installed."""
    print("\n📋 Checking installed packages...")

    # Map package names to import names
    package_mapping = {
        "tensorflow": "tensorflow",
        "tensorflow-hub": "tensorflow_hub",
        "librosa": "librosa",
        "numpy": "numpy",
        "matplotlib": "matplotlib",
        "pandas": "pandas",
        "scikit-learn": "sklearn",
        "seaborn": "seaborn",
    }

    installed = []
    missing = []

    for package_name, import_name in package_mapping.items():
        try:
            __import__(import_name)
            installed.append(package_name)
            print(f"✅ {package_name}")
        except ImportError:
            missing.append(package_name)
            print(f"❌ {package_name}")

    return len(missing) == 0


def create_directory_structure():
    """Ensure all required directories exist."""
    print("\n📁 Checking directory structure...")

    base_dir = Path(__file__).parent
    required_dirs = [
        "data/audio/fish_chewing",
        "data/audio/aerator_noise",
        "data/audio/background",
        "data/processed",
        "models",
        "scripts",
    ]

    for dir_path in required_dirs:
        full_path = base_dir / dir_path
        if not full_path.exists():
            full_path.mkdir(parents=True, exist_ok=True)
            print(f"✅ Created: {dir_path}")
        else:
            print(f"✅ Exists: {dir_path}")

    return True


def check_tensorflow_installation():
    """Check TensorFlow installation and GPU support."""
    print("\n🧠 Checking TensorFlow installation...")

    try:
        # Import TensorFlow dynamically to avoid Pylance warnings
        tf = __import__("tensorflow")  # type: ignore

        print(f"✅ TensorFlow version: {tf.__version__}")

        # Check GPU availability
        gpus = tf.config.list_physical_devices("GPU")
        if gpus:
            print(f"✅ GPU support: {len(gpus)} GPU(s) available")
            for i, gpu in enumerate(gpus):
                print(f"   GPU {i}: {gpu}")
        else:
            print("ℹ️  GPU support: No GPUs found (CPU-only)")

        # Test basic operations
        test_tensor = tf.constant([1, 2, 3, 4])
        print(f"✅ TensorFlow test: {test_tensor.numpy()}")

        return True

    except ImportError:
        print("❌ TensorFlow not installed")
        return False
    except Exception as e:
        print(f"❌ TensorFlow error: {e}")
        return False


def run_quick_tests():
    """Run quick tests to verify installation."""
    print("\n🧪 Running quick tests...")

    try:
        # Test numpy using dynamic import to avoid Pylance warnings
        np = __import__("numpy")  # type: ignore
        arr = np.array([1, 2, 3])
        print(f"✅ NumPy test: {arr.mean()}")

        # Test librosa (without audio file)
        librosa = __import__("librosa")  # type: ignore
        print(f"✅ Librosa version: {librosa.__version__}")

        # Test matplotlib
        matplotlib = __import__("matplotlib")  # type: ignore
        matplotlib.use("Agg")  # Use non-interactive backend
        print(f"✅ Matplotlib version: {matplotlib.__version__}")

        # Test pandas
        pd = __import__("pandas")  # type: ignore
        df = pd.DataFrame({"test": [1, 2, 3]})
        print(f"✅ Pandas test: shape {df.shape}")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def print_next_steps():
    """Print next steps for the user."""
    print("\n🚀 Next Steps:")
    print()
    print("📋 Installation Options:")
    print("   • For training: pip install -r requirements-tensorflow.txt")
    print("   • For inference only: pip install -r requirements-tflite.txt")
    print("   • For audio recording: pip install -r requirements-audio.txt")
    print("   • All at once: pip install -r requirements.txt")
    print()
    print("🔄 Development Workflow:")
    print("1. Collect audio data and place in data/audio/ directories")
    print("2. Update data/labels.csv with your audio file labels")
    print("3. Preprocess audio data:")
    print(
        "   python scripts/preprocess.py --input data/audio --output data/processed"
    )
    print("4. Train the model (requires TensorFlow):")
    print(
        "   python scripts/train.py --data data/processed --output models/yamnet_finetuned"
    )
    print("5. Convert to TensorFlow Lite:")
    print(
        "   python scripts/convert_tflite.py --model models/yamnet_finetuned/final_model.h5 --output models/yamnet.tflite"
    )
    print("6. Run inference:")
    print(
        "   python scripts/infer.py --model models/yamnet.tflite --file your_audio.wav"
    )
    print()
    print("🥧 For Raspberry Pi deployment:")
    print("   • Use TensorFlow Lite only: pip install tflite-runtime")
    print("   • Copy .tflite model file to Pi")
    print("   • Run inference script with --model yamnet.tflite")
    print()
    print("📖 See README.md and example.py for detailed instructions")


def main():
    """Main setup function."""
    print("🦐 AeraSync Feed Setup")
    print("=" * 50)

    all_good = True

    # Check Python version
    if not check_python_version():
        all_good = False

    # Check system dependencies
    if not check_system_dependencies():
        all_good = False

    # Check audio dependencies
    check_audio_dependencies()

    # Create directory structure
    if not create_directory_structure():
        all_good = False

    # Install requirements
    if not install_requirements():
        all_good = False

    # Check installed packages
    if not check_installed_packages():
        all_good = False

    # Check TensorFlow
    if not check_tensorflow_installation():
        all_good = False

    # Run tests
    if not run_quick_tests():
        all_good = False

    print("\n" + "=" * 50)

    if all_good:
        print("🎉 Setup completed successfully!")
        print_next_steps()
    else:
        print("⚠️  Setup completed with some issues.")
        print("   Please resolve the issues above before proceeding.")

    return all_good


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
