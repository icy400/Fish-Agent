# ML Core

只保留了训练/推理核心文件，方便你独立迭代模型，不被前后端干扰。

## 文件说明

- `train/preprocess.py`：音频预处理与特征提取
- `train/train.py`：模型训练（Conv1D + Dense）
- `train/convert_tflite.py`：导出 TFLite
- `inference/audio_infer.py`：离线音频推理（分片）
- `inference/audio_realtime_infer.py`：实时分片推理
- `models/fish_yamnet.tflite`：当前可用模型
- `models/tflite_test_results.json`：模型输入输出形状说明

## 推荐环境

```bash
conda create -n fish-ml python=3.10 -y
conda activate fish-ml
pip install -r requirements-train.txt
```

如果只做推理：

```bash
pip install -r requirements-infer.txt
```
