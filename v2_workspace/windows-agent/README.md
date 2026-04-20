# Windows Agent

Windows 侧仅承担两件事：

1. 本地水听器采集（采集程序在 Windows 环境运行）
2. 将分片上传到 Linux 后端

## 已保留

- `uploader/chunk_uploader.py`
- `uploader/chunk_uploader_config.json`
- `capture/main.py` 及相关 DLL/INI 依赖文件

## 快速运行

```powershell
# 1) 上传代理
cd v2_workspace\windows-agent\uploader
conda create -n fish-win python=3.10 -y
conda activate fish-win
pip install requests
python .\chunk_uploader.py
```

```powershell
# 2) 采集程序（仅 Windows）
cd v2_workspace\windows-agent\capture
python .\main.py
```

## 建议

- 采集程序输出分片到固定目录（与 uploader 的 `watch_dir` 对齐）
- 上传成功后删除分片，缓解 Windows 磁盘压力
