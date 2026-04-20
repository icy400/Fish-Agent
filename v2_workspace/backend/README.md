# Backend Rebuild Entry

这里作为后端重构入口，建议只负责：

1. 接收 Windows 上传的音频分片
2. 调用 `../ml-core/inference` 推理
3. 计算投喂策略状态机
4. 对外提供实时接口（REST + SSE/WebSocket）
5. 记录运行日志并下发设备控制指令

## 当前保留

- `config/application.example.yml`：从旧后端提取的配置样例（含中文注释）

## 建议新后端模块

```text
backend/
├── src/main/java/.../controller
├── src/main/java/.../service
├── src/main/java/.../strategy
├── src/main/java/.../inference
└── src/main/resources/application.yml
```
