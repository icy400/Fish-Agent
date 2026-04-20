# Capture (Windows 水听器采集)

本目录已经包含 Windows 采集所需核心文件，可独立运行：

- `main.py`
- `BRC2.dll`
- `DAQ2.lib`
- `msvcr120.dll`
- `vk70xumcclientconfig.ini`
- `vkcommonconfig.ini`

## 运行方式

```powershell
cd v2_workspace/windows-agent/capture
python .\main.py
```

自动化调用（由 `..\run_agent.py` 使用）：

```powershell
python .\main.py --duration-seconds 6 --auto-start
```

## 说明

1. 该采集程序仅支持 Windows 环境。
2. 可通过环境变量 `HYDROPHONE_WAVE_FILE_PATH` 指定输出音频路径。
3. 建议让采集输出分片到 uploader 的 `watch_dir`。
4. uploader 在 `../uploader`，用于把分片上传到 Linux 后端。
