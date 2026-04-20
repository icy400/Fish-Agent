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

## 说明

1. 该采集程序仅支持 Windows 环境。
2. 建议让采集输出分片到 uploader 的 `watch_dir`。
3. uploader 在 `../uploader`，用于把分片上传到 Linux 后端。
