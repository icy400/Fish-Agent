# v2 Workspace

这个目录是“非破坏式重构”后的干净工作区，目标是：

- 只保留模型训练/推理核心文件
- 给前后端重构留出清晰入口
- 保留 Windows 采集上传代理
- 旧目录暂不删除，便于回查

## 目录结构

```text
v2_workspace/
├── ml-core/              # 模型训练与推理核心
├── backend/              # 后端重构入口（空骨架+配置样例）
├── frontend/             # 前端重构入口（空骨架）
├── windows-agent/        # Windows 侧上传代理与采集说明
└── docs/                 # 结构说明文档
```

## 使用建议

1. 先在 `backend` 跑通最简 FastAPI 骨架。
2. 再在 `frontend` 跑通最简静态页面骨架。
3. 骨架稳定后，再逐步把 `ml-core` 的真实推理接入后端。
