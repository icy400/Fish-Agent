# Frontend Rebuild Entry

这里作为前端重构入口，建议只保留业务可视化：

1. 实时监测状态卡片
2. 分片识别趋势图
3. 投喂策略动作与建议
4. 设备状态与告警
5. 运行日志检索入口（按时间/设备/动作筛选）

## 建议新前端模块

```text
frontend/
├── src/views/RealtimeDashboard
├── src/views/HistoryAndLogs
├── src/api/realtime.ts
└── src/store/realtime.ts
```
