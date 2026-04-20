# Scheme B Quickstart (Windows采集 + Linux识别)

## 1. Linux后端配置

文件：`FishFeedSystem/src/main/resources/application.yml`

核心参数在 `fishfeed.realtime`：

- `upload-dir`：Linux接收到的分片临时目录
- `keep-uploaded-chunks`：是否保留上传分片（调试建议 `true`，生产建议 `false`）
- `python-command`：Python命令（如 `python3`）
- `python-script-path`：推理脚本路径（建议在 Linux 配置为绝对路径）
- `chunk-seconds`：分片秒数（建议与 Windows 端切片一致）
- `decision-window-size`：策略窗口长度
- `fish-segment-threshold`：单段判为鱼声阈值
- `fish-type-threshold`：当前分片判定为鱼声的阈值
- `start-threshold`：触发开始投喂阈值
- `reduce-threshold`：触发减量投喂阈值
- `stop-threshold`：触发停止投喂阈值
- `start-consecutive-windows`：开始投喂连续命中次数
- `stop-consecutive-windows`：停止投喂连续命中次数

## 2. Linux后端接口

- `GET /realtime/start`：启动监测
- `GET /realtime/stop`：暂停监测
- `GET /realtime/reset`：重置统计
- `GET /realtime/data`：当前状态快照
- `GET /realtime/config`：实时配置快照
- `GET /realtime/stream`：SSE实时推送
- `POST /realtime/chunk/upload`：Windows上传音频分片
  - form-data:
    - `file`：音频文件
    - `deviceId`：设备ID（可选）
    - `collectedAt`：采集时间（可选）

## 3. Windows上传代理

文件：

- `Continuous Sampling/chunk_uploader.py`
- `Continuous Sampling/chunk_uploader_config.json`

关键配置项：

- `server_base_url`：Linux API地址（示例 `http://192.168.x.x:8081`）
- `watch_dir`：Windows采集分片目录
- `delete_after_upload`：上传成功后是否删除本地文件
- `scan_interval_seconds`：扫描频率
- `max_retries`：失败重试次数

运行：

```bash
python chunk_uploader.py
```

依赖：

```bash
pip install requests
```

## 4. 前端

前端请求地址可通过环境变量配置：

```bash
VUE_APP_API_BASE_URL=http://<linux-ip>:8081
```

`RealtimeMonitor` 页面会展示：

- 当前识别
- 当前分片鱼声占比
- 决策窗口鱼声占比
- 策略动作（启动/维持/减量/停止）
- 最近分片与设备信息

## 5. 运行日志（排障推荐）

### Linux 后端日志

- 主日志文件：`${user.dir}/logs/fishfeed-app.log`
- 滚动日志：`${user.dir}/logs/fishfeed-app.YYYY-MM-DD.i.log`
- 配置位置：`application.yml > logging` 与 `fishfeed.logging`

建议命令：

```bash
tail -f logs/fishfeed-app.log
```

可重点关注关键字：

- `chunk received`
- `chunk processed`
- `decision action changed`
- `chunk processing failed`
- `[req-`（接口请求轨迹）

### Windows 上传代理日志

- 日志文件：`Continuous Sampling/logs/chunk_uploader.log`（默认）
- 支持按大小滚动（`log_max_bytes` + `log_backup_count`）
- 配置位置：`chunk_uploader_config.json`

建议观察：

- `upload ok`
- `upload failed`
- `give up upload after retries`
