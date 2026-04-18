# Data Directory

This directory contains audio data and labels for training the AeraSync Feed model.

## Structure

```
data/
├── audio/                  # Raw audio files
│   ├── shrimp_chewing/    # Audio clips of shrimp chewing sounds
│   ├── aerator_noise/     # Audio clips of aerator noise
│   └── background/        # Background/ambient sounds
├── processed/             # Preprocessed features
│   ├── features/          # Extracted MFCC features (.npz files)
│   └── images/            # Spectrogram images (optional)
├── labels.csv             # Labels file (filename, label)
└── README.md              # This file
```

## Audio File Naming Convention

To automatically extract labels from filenames, use this naming convention:

- `shrimp_chewing_001.wav` - Shrimp chewing sound #1
- `aerator_noise_001.wav` - Aerator noise sound #1
- `background_001.wav` - Background sound #1

## Labels File Format

Create a `labels.csv` file with the following format:

```csv
filename,label
shrimp_chewing_001.wav,fish_chewing
aerator_noise_001.wav,aerator_noise
background_001.wav,background
```

## Data Collection Guidelines

1. **Recording Setup**:

   - Use a hydrophone for underwater recordings
   - Sample rate: 22050 Hz or higher
   - Format: WAV (uncompressed)
   - Duration: 2-10 seconds per clip

2. **Shrimp Chewing Sounds**:

   - Record during active feeding periods
   - Ensure minimal background noise
   - Multiple feeding sessions for variety

3. **Aerator Noise**:

   - Record at different aerator speeds
   - Various distances from aerator
   - Different water conditions

4. **Background Sounds**:
   - Quiet pond sounds
   - Water movement without feeding/aerator
   - Ambient noise

## Data Quality

- Ensure audio files are not corrupted
- Remove clips with excessive noise or distortion
- Balance the dataset across all classes
- Minimum recommended: 100 clips per class
