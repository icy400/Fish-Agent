"""Shared audio feature helpers used by training and inference."""

import json
from pathlib import Path

from scipy import signal as sp_signal


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

LOWPASS_CUTOFF = 500
LOWPASS_ORDER = 4


def _load_filter_settings():
    if not CONFIG_PATH.exists():
        return LOWPASS_CUTOFF, LOWPASS_ORDER

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

    settings = cfg.get("filter_settings", {})
    return (
        settings.get("lowpass_cutoff_hz", LOWPASS_CUTOFF),
        settings.get("lowpass_order", LOWPASS_ORDER),
    )


LOWPASS_CUTOFF, LOWPASS_ORDER = _load_filter_settings()


def butter_lowpass_filter(data, cutoff=LOWPASS_CUTOFF, fs=22050, order=LOWPASS_ORDER):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    sos = sp_signal.butter(order, normal_cutoff, btype="low", output="sos")
    return sp_signal.sosfilt(sos, data)
