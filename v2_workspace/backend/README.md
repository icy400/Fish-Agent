# Simple Backend (FastAPI)

这是最简可运行后端骨架，目标是先跑通：

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
conda create -n fish-simple python=3.10 -y
conda activate fish-simple
pip install -r requirements.txt
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

## 推理模式

`config/backend_config.json` 中：

- `inference.mode = "mock"`：无需模型依赖，最快跑通
- `inference.mode = "python_script"`：调用真实推理脚本
