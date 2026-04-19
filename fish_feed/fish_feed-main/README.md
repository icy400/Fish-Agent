# AeraSync Feed: Shrimp Feeder Audio Classification

## Overview

AeraSync Feed is a project aimed at improving automatic shrimp feeder systems in Ecuador's aquaculture industry. The system uses a hydrophone and Raspberry Pi to distinguish shrimp chewing sounds from aerator noise, enabling synchronized feeding to prevent starvation and reduce organic waste accumulation. This repository contains the code for training and deploying an audio classification model using TensorFlow.

## Problem

Current feeder algorithms misinterpret aerator noise as shrimp chewing, causing unsynchronized feeding. This leads to shrimp starvation or excess feed, increasing cyanobacteria proliferation and pond mortality.

## Solution

We retrain a deep learning model using TensorFlow to classify audio from a laboratory pond, leveraging supervised learning with labeled data. The model is fine-tuned from a pre-trained YamNet model and deployed on a Raspberry Pi using TensorFlow Lite for real-time feeder control.

## Requirements

- **Hardware**:
  - Raspberry Pi (e.g., Raspberry Pi 4)
  - Hydrophone for audio capture
- **Software**:
  - Python 3.8+
  - TensorFlow 2.x
  - tensorflow-io
  - Librosa
  - NumPy
  - TensorFlow Lite (for Raspberry Pi deployment)

Install dependencies:

```bash
pip install tensorflow tensorflow-io librosa numpy
```

## Project Structure

```
aerasync_feed/
├── data/                   # Audio clips and labeled datasets
├── models/                 # Trained models and TensorFlow Lite outputs
├── scripts/                # Python scripts for data processing and training
│   ├── preprocess.py       # Audio preprocessing (spectrograms/MFCCs)
│   ├── train.py            # Model training with YamNet fine-tuning
│   ├── convert_tflite.py   # Convert model to TensorFlow Lite
│   └── infer.py            # Real-time inference on Raspberry Pi
├── README.md               # This file
└── requirements.txt        # Python dependencies
```

## Setup Instructions

1. **Data Collection**:

   - Record audio in a laboratory pond with shrimp and aerators using a hydrophone connected to a Raspberry Pi.
   - Save clips in `data/` (e.g., WAV format).

2. **Labeling**:

   - Manually label audio clips as "shrimp_chewing," "aerator_noise," or other categories.
   - Store labeled data in `data/` (e.g., as CSV or JSON).

3. **Preprocessing**:

   - Run `scripts/preprocess.py` to convert audio into spectrograms or MFCCs:
     ```bash
     python scripts/preprocess.py --input data/audio --output data/processed
     ```

4. **Training**:

   - Use Google Colab (free GPU) or a local machine to run `scripts/train.py`:
     ```bash
     python scripts/train.py --data data/processed --output models/yamnet_finetuned
     ```
   - The script fine-tunes the YamNet model on the labeled dataset.

5. **Model Conversion**:

   - Convert the trained model to TensorFlow Lite for Raspberry Pi:
     ```bash
     python scripts/convert_tflite.py --model models/yamnet_finetuned --output models/yamnet.tflite
     ```

6. **Deployment**:
   - Deploy the TensorFlow Lite model on the Raspberry Pi:
     ```bash
     python scripts/infer.py --model models/yamnet.tflite
     ```
   - Integrate outputs with the feeder control system.

## Usage

- **Training**: Use `train.py` with a labeled dataset to fine-tune the model.
- **Inference**: Run `infer.py` on the Raspberry Pi to classify audio in real-time and control feeding.
- **Monitoring**: Validate model performance using a test dataset to ensure accurate sound classification.

## Contributing

Contributions are welcome! Please:

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Commit changes (`git commit -m "Add your feature"`).
4. Push to the branch (`git push origin feature/your-feature`).
5. Open a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with TensorFlow and TensorFlow Lite for efficient audio classification.
- Uses YamNet for transfer learning.
- Developed to support sustainable shrimp farming in Ecuador.


## Live Linux Service + Web Dashboard

This repository now includes a lightweight API service and dashboard for cross-platform deployment:

- **Linux backend API**: `server/app.py`
- **Web dashboard**: `web/index.html`
- **Windows collector integration target endpoint**: `POST /api/v1/analyze`

Start on Linux:

```bash
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Open dashboard:

```text
http://<linux-host>:8000/
```

API endpoints:

- `GET /api/v1/health`
- `GET /api/v1/results?limit=50`
- `POST /api/v1/analyze` (multipart form: `file`, `device_id`, `chunk_id`, `timestamp_utc`, `sample_rate`, `channel`)
- `WS /ws/live` (real-time inference pushes)


## Cross-Platform Startup Commands (Windows + Linux)

### 1) Linux (inference service + web dashboard)

```bash
cd fish_feed/fish_feed-main
python -m pip install -r requirements-base.txt
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

After startup:

- Health: `http://<linux-host>:8000/api/v1/health`
- Dashboard: `http://<linux-host>:8000/`

### 2) Windows (hydrophone collector)

Open PowerShell/CMD and run:

```powershell
cd "Continuous Sampling"
py -m pip install requests
py main.py
```

If `py` is not available, replace with `python`.

Before starting collection, set the Linux endpoint in `Continuous Sampling/main.py`:

```python
UPLOAD_URL = "http://<linux-host>:8000/api/v1/analyze"
```

Then input the capture duration when prompted. The script will:

1. collect hydrophone data through `BRC2.dll`,
2. upload chunks to Linux in real time,
3. still save a full local WAV file (default: `D:\ceshi.wav`).
