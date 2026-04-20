# Windows Agent

Windows 侧现在只需启动一个入口文件：

1. 本地水听器采集（调用 `capture/main.py`）
2. 自动上传分片（拉起 `uploader/chunk_uploader.py`）
3. 轮询 Linux 后端采集指令（开始/停止）
4. 上报运行心跳到后端（前端可看到在线状态）

## 已保留

- `run_agent.py`（统一入口）
- `agent_config.json`（统一配置）
- `uploader/chunk_uploader.py` + `uploader/chunk_uploader_config.json`
- `capture/main.py` + DLL/INI 依赖文件

## 快速运行

```powershell
# 1) 环境安装
cd v2_workspace\windows-agent
conda create -n fish-win python=3.10 -y
conda activate fish-win
pip install requests

# 2) 一键启动（内部会自动拉起采集+上传）
python .\run_agent.py
```

## 建议

- `agent_config.json` 中的 `server_base_url` 改成 Linux 后端地址。
- `uploader/chunk_uploader_config.json` 的 `watch_dir` 与采集输出目录保持一致。
- 前端页面点击“开始采集/停止采集”即可远程控制采集状态。
