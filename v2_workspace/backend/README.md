# Simple Backend (FastAPI)

这是 Linux 侧最简可运行后端，目标是先跑通：

1. 实时状态接口
2. 分片上传接口
3. 简化策略决策
4. 运行日志

## 目录

```text
backend/
├── app/main.py
├── config/backend_config.json
└── requirements.txt
```

## 快速运行

```bash
cd v2_workspace/backend
conda create -n fish-linux python=3.10 -y
conda activate fish-linux
pip install -r requirements.txt

# 如需真实模型推理，再安装：
pip install -r ../ml-core/requirements-infer.txt

uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

## 关键接口

- `GET /health`
- `GET /realtime/start`
- `GET /realtime/stop`
- `GET /realtime/reset`
- `GET /realtime/data`
- `GET /realtime/config`
- `POST /realtime/chunk/upload`
- `GET /agent/collect/start`（下发开始采集指令）
- `GET /agent/collect/stop`（下发停止采集指令）
- `GET /agent/control`（Windows 代理轮询）
- `GET /agent/state`（前端查看代理状态）
- `POST /agent/heartbeat`（Windows 代理心跳）

## 推理模式

`config/backend_config.json` 中：

- `inference.mode = "mock"`：无需模型依赖，最快跑通
- `inference.mode = "python_script"`：调用真实推理脚本
- `inference.script_path`：默认指向 `../ml-core/inference/audio_realtime_infer.py`
- `agent_control.*`：Windows 代理心跳超时和轮询提示参数

## 日志文件

- 默认日志：`runtime/logs/backend.log`
- 支持滚动切分（`max_bytes` + `backup_count`）
