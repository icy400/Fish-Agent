# v2 Workspace（融合版）

`v2_workspace` 是当前项目唯一需要保留的运行目录，已经融合了两份代码的核心能力：

- Windows 水听器采集与分片上传
- Linux 后端实时识别与投喂策略
- 前端实时展示
- 模型训练与推理核心

目标是围绕“根据实时鱼群声音实现精准投喂”。

## 目录结构

```text
v2_workspace/
├── backend/                 # Linux 后端（FastAPI，含日志与策略）
├── frontend/                # 前端静态页面（实时状态展示）
├── ml-core/                 # 声学模型训练/推理核心文件
├── windows-agent/
│   ├── run_agent.py         # Windows 单入口代理（采集+上传+控制轮询）
│   ├── capture/             # Windows 采集程序（仅 Windows 可运行）
│   └── uploader/            # Windows 分片上传代理
└── docs/
```

## Linux 运行命令

```bash
# 1) 后端环境
cd v2_workspace/backend
conda create -n fish-linux python=3.10 -y
conda activate fish-linux
pip install -r requirements.txt

# 2) 如果要用真实模型推理，再安装推理依赖
pip install -r ../ml-core/requirements-infer.txt

# 3) 启动后端
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

```bash
# 4) 启动前端（另开一个终端）
cd v2_workspace/frontend
python -m http.server 5173
```

前端访问：`http://127.0.0.1:5173`

## Windows 运行命令

```powershell
# 1) Windows 环境
cd v2_workspace\windows-agent
conda create -n fish-win python=3.10 -y
conda activate fish-win
pip install requests

# 2) 一键启动 Windows 代理（内部自动拉起采集+上传）
python .\run_agent.py
```

## 关键配置

- `backend/config/backend_config.json`
  - 每个配置项都已包含中文注释（`_comments`）。
  - 可切换 `inference.mode`：
    - `mock`：快速联调
    - `python_script`：真实模型推理
- `windows-agent/uploader/chunk_uploader_config.json`
  - 每个配置项都已包含中文注释（`_comments`）。
  - 重点改 `server_base_url`、`watch_dir`、`delete_after_upload`。
- `windows-agent/agent_config.json`
  - 每个配置项都已包含中文注释（`_comments`）。
  - 重点改 `server_base_url`，其余默认可直接联调。

## 日志位置

- Linux 后端日志：`v2_workspace/backend/runtime/logs/backend.log`
- Windows 上传日志：`v2_workspace/windows-agent/uploader/logs/chunk_uploader.log`
- Windows 统一代理日志：`v2_workspace/windows-agent/logs/windows_agent.log`

## 推荐启动顺序

1. Linux 启动后端与前端。
2. Windows 启动 `run_agent.py`（只需一次）。
3. 前端点击“开始采集/停止采集”远程下发指令。
4. 前端观察实时识别结果与投喂策略动作（`FEED_START/FEED_HOLD/FEED_REDUCE/FEED_STOP`）。
