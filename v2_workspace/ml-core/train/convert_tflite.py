#!/usr/bin/env python3
"""
Model conversion script for AeraSync Feed project.
Converts trained TensorFlow model to TensorFlow Lite for Raspberry Pi deployment.
"""

import os
import argparse
import tensorflow as tf
import numpy as np
import json
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def convert_to_tflite(
    model_path, output_path, quantize=True, representative_dataset=None
):
    """
    Convert TensorFlow model to TensorFlow Lite format.

    Args:
        model_path (str): Path to trained TensorFlow model
        output_path (str): Output path for TFLite model
        quantize (bool): Whether to apply quantization
        representative_dataset: Representative dataset for quantization

    Returns:
        str: Path to converted TFLite model
    """
    logger.info(f"Loading model from: {model_path}")

    # Load the trained model
    if model_path.endswith(".h5"):
        model = tf.keras.models.load_model(model_path)
    else:
        model = tf.saved_model.load(model_path)

    # Create TensorFlow Lite converter
    converter = tf.lite.TFLiteConverter.from_keras_model(model)

    if quantize:
        logger.info("Applying quantization...")

        # Set quantization options
        converter.optimizations = [tf.lite.Optimize.DEFAULT]

        if representative_dataset is not None:
            logger.info("Using representative dataset for quantization...")
            converter.representative_dataset = representative_dataset

            # Enable full integer quantization (optional)
            # converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
            # converter.inference_input_type = tf.uint8
            # converter.inference_output_type = tf.uint8

    # Convert the model
    logger.info("Converting model to TensorFlow Lite...")
    try:
        tflite_model = converter.convert()
    except Exception as e:
        logger.error(f"Conversion failed: {str(e)}")
        # Try without quantization as fallback
        logger.info("Retrying without quantization...")
        converter.optimizations = []
        tflite_model = converter.convert()

    # Save the TFLite model
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(tflite_model)

    logger.info(f"TensorFlow Lite model saved to: {output_path}")

    # Get model size
    model_size = len(tflite_model) / (1024 * 1024)  # Size in MB
    logger.info(f"Model size: {model_size:.2f} MB")

    return str(output_path)


def create_representative_dataset(data_dir, num_samples=100):
    """
    Create representative dataset for quantization.

    Args:
        data_dir (str): Directory containing preprocessed features
        num_samples (int): Number of samples to use

    Returns:
        function: Representative dataset generator
    """
    features_dir = Path(data_dir) / "features"

    if not features_dir.exists():
        logger.warning(f"Features directory not found: {features_dir}")
        return None

    # Load sample features
    feature_files = list(features_dir.glob("*.npz"))[:num_samples]

    if not feature_files:
        logger.warning("No feature files found for representative dataset")
        return None

    samples = []
    for feature_file in feature_files:
        try:
            data = np.load(feature_file)
            mfccs = data["mfccs"]

            # Pad or truncate to fixed length
            target_length = 128
            if mfccs.shape[1] < target_length:
                mfccs = np.pad(
                    mfccs,
                    ((0, 0), (0, target_length - mfccs.shape[1])),
                    mode="constant",
                )
            else:
                mfccs = mfccs[:, :target_length]

            samples.append(mfccs.T.astype(np.float32))

        except Exception as e:
            logger.warning(f"Error loading {feature_file}: {str(e)}")

    if not samples:
        return None

    def representative_dataset_gen():
        for sample in samples:
            yield [np.expand_dims(sample, axis=0)]

    logger.info(f"Created representative dataset with {len(samples)} samples")
    return representative_dataset_gen


def test_tflite_model(tflite_path, test_data=None):
    """
    Test the converted TensorFlow Lite model.

    Args:
        tflite_path (str): Path to TFLite model
        test_data (np.array): Optional test data

    Returns:
        dict: Test results
    """
    logger.info(f"Testing TensorFlow Lite model: {tflite_path}")

    # Load TFLite model and allocate tensors
    interpreter = tf.lite.Interpreter(model_path=tflite_path)
    interpreter.allocate_tensors()

    # Get input and output tensors
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    logger.info("Model Input Details:")
    for detail in input_details:
        logger.info(
            f"  Name: {detail['name']}, Shape: {detail['shape']}, Type: {detail['dtype']}"
        )

    logger.info("Model Output Details:")
    for detail in output_details:
        logger.info(
            f"  Name: {detail['name']}, Shape: {detail['shape']}, Type: {detail['dtype']}"
        )

    results = {
        "input_shape": input_details[0]["shape"].tolist(),
        "output_shape": output_details[0]["shape"].tolist(),
        "input_dtype": str(input_details[0]["dtype"]),
        "output_dtype": str(output_details[0]["dtype"]),
    }

    # Test with sample data if provided
    if test_data is not None:
        logger.info("Running inference test...")

        # Ensure test data matches expected input shape
        input_shape = input_details[0]["shape"]
        if test_data.shape != tuple(input_shape):
            logger.warning(
                f"Test data shape {test_data.shape} doesn't match expected {input_shape}"
            )
            return results

        # Set input tensor
        interpreter.set_tensor(input_details[0]["index"], test_data)

        # Run inference
        interpreter.invoke()

        # Get output
        output_data = interpreter.get_tensor(output_details[0]["index"])

        results["test_output_shape"] = output_data.shape
        results["test_prediction"] = output_data.tolist()

        logger.info(f"Test completed. Output shape: {output_data.shape}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert TensorFlow model to TensorFlow Lite"
    )
    parser.add_argument(
        "--model",
        "-m",
        required=True,
        help="Path to trained TensorFlow model (.h5 or SavedModel directory)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output path for TensorFlow Lite model (.tflite)",
    )
    parser.add_argument(
        "--data",
        "-d",
        help="Directory containing preprocessed data for representative dataset",
    )
    parser.add_argument(
        "--no-quantize",
        action="store_true",
        help="Disable quantization optimization",
    )
    parser.add_argument(
        "--test", action="store_true", help="Test the converted model"
    )

    args = parser.parse_args()

    if not os.path.exists(args.model):
        logger.error(f"Model file does not exist: {args.model}")
        return

    # Create representative dataset if data directory provided
    representative_dataset = None
    if args.data and not args.no_quantize:
        representative_dataset = create_representative_dataset(args.data)

    # Convert model
    tflite_path = convert_to_tflite(
        model_path=args.model,
        output_path=args.output,
        quantize=not args.no_quantize,
        representative_dataset=representative_dataset,
    )

    # Test converted model
    if args.test:
        test_results = test_tflite_model(tflite_path)

        # Save test results
        results_path = Path(args.output).parent / "tflite_test_results.json"
        with open(results_path, "w") as f:
            json.dump(test_results, f, indent=2)

        logger.info(f"Test results saved to: {results_path}")

    logger.info("Conversion completed successfully!")


if __name__ == "__main__":
    main()
