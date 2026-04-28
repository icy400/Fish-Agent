"""Upload audio file to Fish Agent server with retry logic."""

import os
import sys
import time
import hashlib
import argparse
from pathlib import Path

import requests
import yaml


def load_config(config_path=None):
    if config_path is None:
        config_path = Path(__file__).resolve().parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def upload_file(filepath, server_url, retry_max=3, retry_delay_sec=5):
    """Upload a WAV file to the Fish Agent server. Returns (success, response_json)."""
    path = Path(filepath)
    if not path.exists():
        print(f"文件不存在: {filepath}")
        return False, None

    file_size_mb = path.stat().st_size / (1024 * 1024)
    print(f"上传文件: {path.name} ({file_size_mb:.1f} MB)")
    print(f"目标服务器: {server_url}")

    for attempt in range(retry_max):
        try:
            print(f"上传中... (第 {attempt + 1}/{retry_max} 次)")
            with open(path, "rb") as f:
                resp = requests.post(
                    f"{server_url}/api/files/upload",
                    files={"file": (path.name, f, "audio/wav")},
                    data={"source": "hydrophone"},
                    timeout=(10, 600),  # 10s connect, 10min read
                )

            if resp.status_code in (200, 201):
                data = resp.json()
                print(f"上传成功! ID={data.get('id')}, 状态={data.get('status')}")
                if data.get("fish_count") is not None:
                    print(f"鱼声片段数: {data.get('fish_count')} | 投喂强度: {data.get('feeding_level')}")
                return True, data

            if resp.status_code >= 500:
                print(f"服务器错误 {resp.status_code}, 稍后重试...")
                time.sleep(retry_delay_sec * (2 ** attempt))
                continue

            print(f"上传失败: HTTP {resp.status_code} — {resp.text}")
            return False, None

        except requests.exceptions.RequestException as e:
            print(f"网络错误: {e}")
            if attempt < retry_max - 1:
                delay = retry_delay_sec * (2 ** attempt)
                print(f"将在 {delay}s 后重试...")
                time.sleep(delay)
            else:
                print("已达最大重试次数，放弃上传")
                return False, None

    return False, None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload audio file to Fish Agent server")
    parser.add_argument("file", help="Path to WAV file")
    parser.add_argument("--server", "-s", help="Server URL (overrides config)")
    parser.add_argument("--config", "-c", help="Config file path")
    args = parser.parse_args()

    cfg = load_config(args.config)
    server_url = args.server or cfg["upload"]["server_url"]

    success, _ = upload_file(
        args.file,
        server_url,
        retry_max=cfg["upload"].get("retry_max", 3),
        retry_delay_sec=cfg["upload"].get("retry_delay_sec", 5),
    )

    sys.exit(0 if success else 1)
