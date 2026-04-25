# Simple Frontend (Vanilla HTML/JS)

这是最简前端骨架，不需要 npm 构建，直接静态文件运行。

## 文件

```text
frontend/
├── index.html
├── app.js
├── style.css
└── config.js
```

## 快速运行

```bash
cd v2_workspace/frontend
python -m http.server 5173
```

浏览器访问：

- `http://127.0.0.1:5173`

如果后端不是本机：

- 修改 `config.js` 里的 `apiBaseUrl`

## 页面控制说明

- `开始采集`：同时触发后端监测启动 + 下发 Windows 采集开始指令
- `停止采集`：同时下发 Windows 停止采集指令 + 暂停后端监测
- 面板内会显示 `采集代理状态` 与 `采集指令`
