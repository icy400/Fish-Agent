# Core File Map

## 保留到 `v2_workspace` 的核心文件映射

### 训练链路

- `fish_feed/fish_feed-main/scripts/preprocess.py`
  -> `v2_workspace/ml-core/train/preprocess.py`
- `fish_feed/fish_feed-main/scripts/train.py`
  -> `v2_workspace/ml-core/train/train.py`
- `fish_feed/fish_feed-main/scripts/convert_tflite.py`
  -> `v2_workspace/ml-core/train/convert_tflite.py`

### 推理链路

- `fish_feed/FishAcousticPerceptionSystem/FishFeedSystem/src/main/resources/python/audio_infer.py`
  -> `v2_workspace/ml-core/inference/audio_infer.py`
- `fish_feed/FishAcousticPerceptionSystem/FishFeedSystem/src/main/resources/python/audio_realtime_infer.py`
  -> `v2_workspace/ml-core/inference/audio_realtime_infer.py`

### 模型文件

- `fish_feed/FishAcousticPerceptionSystem/FishFeedSystem/src/main/resources/model/fish_yamnet.tflite`
  -> `v2_workspace/ml-core/models/fish_yamnet.tflite`
- `fish_feed/FishAcousticPerceptionSystem/FishFeedSystem/src/main/resources/model/tflite_test_results.json`
  -> `v2_workspace/ml-core/models/tflite_test_results.json`

### Windows 上传代理

- `Continuous Sampling/chunk_uploader.py`
  -> `v2_workspace/windows-agent/uploader/chunk_uploader.py`
- `Continuous Sampling/chunk_uploader_config.json`
  -> `v2_workspace/windows-agent/uploader/chunk_uploader_config.json`
