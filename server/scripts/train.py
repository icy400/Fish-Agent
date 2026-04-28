#!/usr/bin/env python3
"""
Model training script for AeraSync Feed project.
Fine-tunes YamNet model for shrimp chewing vs aerator noise classification.
"""

import os
import argparse
import numpy as np
import tensorflow as tf
import tensorflow_hub as hub
import pandas as pd
import json
import logging
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix
import matplotlib.pyplot as plt
import seaborn as sns

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# YamNet model URL
YAMNET_MODEL_HANDLE = "https://tfhub.dev/google/yamnet/1"


def load_yamnet_model():
    """Load pre-trained YamNet model from TensorFlow Hub."""
    logger.info("Loading YamNet model...")
    yamnet_model = hub.load(YAMNET_MODEL_HANDLE)
    return yamnet_model


def load_dataset(data_dir, labels_file=None):
    """
    Load preprocessed audio features and labels.

    Args:
        data_dir (str): Directory containing preprocessed features
        labels_file (str): Optional labels file (CSV or JSON)

    Returns:
        tuple: (features, labels) arrays
    """
    features_dir = Path(data_dir) / "features"

    if not features_dir.exists():
        raise ValueError(f"Features directory not found: {features_dir}")

    features_list = []
    labels_list = []
    filenames = []

    # Load features from .npz files
    for feature_file in features_dir.glob("*.npz"):
        try:
            data = np.load(feature_file)

            # Use MFCCs as primary features
            mfccs = data["mfccs"]
            # Pad or truncate to fixed length (e.g., 128 time steps)
            target_length = 128
            if mfccs.shape[1] < target_length:
                # Pad with zeros
                mfccs = np.pad(
                    mfccs,
                    ((0, 0), (0, target_length - mfccs.shape[1])),
                    mode="constant",
                )
            else:
                # Truncate
                mfccs = mfccs[:, :target_length]

            features_list.append(mfccs.T)  # Transpose to (time, features)
            filenames.append(feature_file.stem.replace("_features", ""))

            # Extract label from filename (assumes format: label_filename.ext)
            # Modify this logic based on your labeling scheme
            # filename_parts = feature_file.stem.split("_")
            # if len(filename_parts) > 1 and filename_parts[0] in [
            #     "fish",
            #     "aerator",
            #     "background",
            # ]:
            #     labels_list.append(filename_parts[0])
            # else:
            #     labels_list.append("unknown")  # Default label
            # 修改后（只识别 fish 和 background）
            stem = feature_file.stem.lower()
            if any(keyword in stem for keyword in ["fish", "chewing", "feeding"]):
                labels_list.append("fish")
            else:
                labels_list.append("background")

        except Exception as e:
            logger.warning(f"Error loading {feature_file}: {str(e)}")

    if not features_list:
        raise ValueError("No valid feature files found")

    # Load external labels file if provided
    if labels_file and os.path.exists(labels_file):
        logger.info(f"Loading labels from: {labels_file}")
        if labels_file.endswith(".csv"):
            label_data = pd.read_csv(labels_file)
            # Assuming columns: 'filename', 'label'
            label_dict = dict(zip(label_data["filename"], label_data["label"]))
            labels_list = [
                label_dict.get(fname, "unknown") for fname in filenames
            ]
        elif labels_file.endswith(".json"):
            with open(labels_file, "r") as f:
                label_dict = json.load(f)
            labels_list = [
                label_dict.get(fname, "unknown") for fname in filenames
            ]

    return np.array(features_list), np.array(labels_list), filenames


def create_model(input_shape, num_classes, yamnet_model=None):
    """
    Create a model for audio classification.

    Args:
        input_shape (tuple): Input shape for features
        num_classes (int): Number of output classes
        yamnet_model: Pre-trained YamNet model (optional)

    Returns:
        tf.keras.Model: Compiled model
    """
    if yamnet_model is not None:
        # Use YamNet embeddings as base
        logger.info("Creating model with YamNet embeddings...")

        # Create a model that uses YamNet embeddings
        inputs = tf.keras.Input(shape=input_shape)

        # For YamNet, we need to process raw audio, but here we're using MFCC features
        # So we'll create a custom model architecture

        # CNN layers for feature extraction
        x = tf.keras.layers.Conv1D(64, 3, activation="relu")(inputs)
        x = tf.keras.layers.MaxPooling1D(2)(x)
        x = tf.keras.layers.Conv1D(128, 3, activation="relu")(x)
        x = tf.keras.layers.MaxPooling1D(2)(x)
        x = tf.keras.layers.Conv1D(256, 3, activation="relu")(x)
        x = tf.keras.layers.GlobalMaxPooling1D()(x)

        # Dense layers
        x = tf.keras.layers.Dense(512, activation="relu")(x)
        x = tf.keras.layers.Dropout(0.5)(x)
        x = tf.keras.layers.Dense(256, activation="relu")(x)
        x = tf.keras.layers.Dropout(0.3)(x)

        # Output layer
        outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(x)

        model = tf.keras.Model(inputs, outputs)

    else:
        # Simple CNN model without YamNet
        logger.info("Creating simple CNN model...")

        model = tf.keras.Sequential(
            [
                tf.keras.layers.Input(shape=input_shape),
                tf.keras.layers.Conv1D(64, 3, activation="relu"),
                tf.keras.layers.MaxPooling1D(2),
                tf.keras.layers.Conv1D(128, 3, activation="relu"),
                tf.keras.layers.MaxPooling1D(2),
                tf.keras.layers.Conv1D(256, 3, activation="relu"),
                tf.keras.layers.GlobalMaxPooling1D(),
                tf.keras.layers.Dense(512, activation="relu"),
                tf.keras.layers.Dropout(0.5),
                tf.keras.layers.Dense(256, activation="relu"),
                tf.keras.layers.Dropout(0.3),
                tf.keras.layers.Dense(num_classes, activation="softmax"),
            ]
        )

    # Compile model
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    return model


def plot_training_history(history, output_dir):
    """Plot and save training history."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

    # Plot accuracy
    ax1.plot(history.history["accuracy"], label="Training Accuracy")
    ax1.plot(history.history["val_accuracy"], label="Validation Accuracy")
    ax1.set_title("Model Accuracy")
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("Accuracy")
    ax1.legend()

    # Plot loss
    ax2.plot(history.history["loss"], label="Training Loss")
    ax2.plot(history.history["val_loss"], label="Validation Loss")
    ax2.set_title("Model Loss")
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Loss")
    ax2.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "training_history.png"), dpi=300)
    plt.close()


def plot_confusion_matrix(y_true, y_pred, class_names, output_dir):
    """Plot and save confusion matrix."""
    cm = confusion_matrix(y_true, y_pred)

    plt.figure(figsize=(8, 6))
    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=class_names,
        yticklabels=class_names,
    )
    plt.title("Confusion Matrix")
    plt.xlabel("Predicted")
    plt.ylabel("Actual")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "confusion_matrix.png"), dpi=300)
    plt.close()


def train_model(
    data_dir, output_dir, labels_file=None, epochs=50, batch_size=32
):
    """
    Train the audio classification model.

    Args:
        data_dir (str): Directory containing preprocessed data
        output_dir (str): Directory to save trained model
        labels_file (str): Optional labels file
        epochs (int): Number of training epochs
        batch_size (int): Training batch size
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load dataset
    logger.info("Loading dataset...")
    features, labels, filenames = load_dataset(data_dir, labels_file)

    logger.info(f"Loaded {len(features)} samples")
    logger.info(f"Feature shape: {features.shape}")
    logger.info(
        f"Labels distribution: {np.unique(labels, return_counts=True)}"
    )

    # Encode labels
    label_encoder = LabelEncoder()
    encoded_labels = label_encoder.fit_transform(labels)
    num_classes = 2

    logger.info(f"Number of classes: {num_classes}")
    logger.info(f"Classes: {label_encoder.classes_}")

    # Save label encoder
    label_encoder_path = output_path / "label_encoder.json"
    with open(label_encoder_path, "w") as f:
        json.dump(
            {
                "classes": label_encoder.classes_.tolist(),
                "class_to_index": {
                    cls: idx for idx, cls in enumerate(label_encoder.classes_)
                },
            },
            f,
            indent=2,
        )

    # Split dataset
    X_train, X_test, y_train, y_test = train_test_split(
        features,
        encoded_labels,
        test_size=0.2,
        random_state=42,
        stratify=encoded_labels,
    )

    X_train, X_val, y_train, y_val = train_test_split(
        X_train, y_train, test_size=0.2, random_state=42, stratify=y_train
    )

    logger.info(f"Training set: {X_train.shape[0]} samples")
    logger.info(f"Validation set: {X_val.shape[0]} samples")
    logger.info(f"Test set: {X_test.shape[0]} samples")

    # Load YamNet model (optional)
    try:
        yamnet_model = load_yamnet_model()
    except Exception as e:
        logger.warning(f"Could not load YamNet model: {str(e)}")
        yamnet_model = None

    # Create and compile model
    input_shape = features.shape[1:]
    model = create_model(input_shape, num_classes, yamnet_model)

    logger.info("Model architecture:")
    model.summary()

    # Define callbacks
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=10, restore_best_weights=True
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=5, min_lr=1e-7
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(output_path / "best_model.h5"),
            monitor="val_accuracy",
            save_best_only=True,
            verbose=1,
        ),
    ]

    # Train model
    logger.info("Starting training...")
    history = model.fit(
        X_train,
        y_train,
        batch_size=batch_size,
        epochs=epochs,
        validation_data=(X_val, y_val),
        callbacks=callbacks,
        verbose=1,
    )

    # Evaluate model
    logger.info("Evaluating model...")
    test_loss, test_accuracy = model.evaluate(X_test, y_test, verbose=0)
    logger.info(f"Test accuracy: {test_accuracy:.4f}")

    # Make predictions
    y_pred = model.predict(X_test)
    y_pred_classes = np.argmax(y_pred, axis=1)

    # Classification report
    report = classification_report(
        y_test,
        y_pred_classes,
        target_names=label_encoder.classes_,
        output_dict=True,
    )

    logger.info("Classification Report:")
    print(
        classification_report(
            y_test, y_pred_classes, target_names=label_encoder.classes_
        )
    )

    # Save results
    results = {
        "test_accuracy": float(test_accuracy),
        "test_loss": float(test_loss),
        "classification_report": report,
        "training_params": {
            "epochs": epochs,
            "batch_size": batch_size,
            "num_classes": num_classes,
            "input_shape": input_shape,
        },
    }

    results_path = output_path / "training_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    # Save final model
    model.save(str(output_path / "final_model.h5"))

    # Plot results
    plot_training_history(history, str(output_path))
    plot_confusion_matrix(
        y_test, y_pred_classes, label_encoder.classes_, str(output_path)
    )

    logger.info(f"Training completed! Model saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Train audio classification model"
    )
    parser.add_argument(
        "--data",
        "-d",
        required=True,
        help="Directory containing preprocessed data",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for trained model",
    )
    parser.add_argument("--labels", "-l", help="Labels file (CSV or JSON)")
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
        help="Number of training epochs (default: 50)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Training batch size (default: 32)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.data):
        logger.error(f"Data directory does not exist: {args.data}")
        return

    train_model(
        args.data, args.output, args.labels, args.epochs, args.batch_size
    )


if __name__ == "__main__":
    main()
