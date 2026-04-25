const cfg = window.APP_CONFIG || {};
const API_BASE = (cfg.apiBaseUrl || "http://127.0.0.1:8081").replace(/\/$/, "");
const REFRESH_MS = Number(cfg.refreshMs || 2000);

const ids = [
  "status",
  "currentType",
  "confidence",
  "totalCount",
  "fishRatio",
  "windowFishRatio",
  "baselineFishRatio",
  "relativeFishDelta",
  "decisionAction",
  "intensity",
  "suggestion",
  "strategyReason",
  "lastChunkName",
  "lastChunkAt",
  "lastDeviceId",
  "agentStatus",
  "collectCommand",
];

const el = {};
ids.forEach((id) => (el[id] = document.getElementById(id)));
const waterfallCanvas = document.getElementById("waterfallCanvas");
const waterfallStatus = document.getElementById("waterfallStatus");
const judgmentBody = document.getElementById("judgmentBody");

function ratioText(v) {
  if (v === undefined || v === null) return "-";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function signedRatioText(v) {
  if (v === undefined || v === null) return "-";
  const num = Number(v) * 100;
  return `${num >= 0 ? "+" : ""}${num.toFixed(1)}%`;
}

function confText(v) {
  if (v === undefined || v === null) return "-";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function applyData(data) {
  el.status.textContent = data.status ?? "-";
  el.currentType.textContent = data.currentType ?? "-";
  el.confidence.textContent = confText(data.confidence);
  el.totalCount.textContent = data.totalCount ?? "-";
  el.fishRatio.textContent = ratioText(data.fishRatio);
  el.windowFishRatio.textContent = ratioText(data.windowFishRatio);
  el.baselineFishRatio.textContent = ratioText(data.baselineFishRatio);
  el.relativeFishDelta.textContent = signedRatioText(data.relativeFishDelta);
  el.decisionAction.textContent = data.decisionAction ?? "-";
  el.intensity.textContent = data.intensity ?? "-";
  el.suggestion.textContent = data.suggestion ?? "-";
  el.strategyReason.textContent = data.strategyReason ?? "-";
  el.lastChunkName.textContent = data.lastChunkName ?? "-";
  el.lastChunkAt.textContent = data.lastChunkAt ?? "-";
  el.lastDeviceId.textContent = data.lastDeviceId ?? "-";
}

function applyAgent(agent) {
  el.agentStatus.textContent = agent?.agentStatus ?? "-";
  el.collectCommand.textContent = agent?.collectEnabled ? "START" : "STOP";
}

function colorForWaterfall(v) {
  const x = Math.max(0, Math.min(1, Number(v) || 0));
  if (x < 0.25) {
    const t = x / 0.25;
    return `rgb(${Math.round(8 + t * 12)}, ${Math.round(16 + t * 60)}, ${Math.round(28 + t * 70)})`;
  }
  if (x < 0.5) {
    const t = (x - 0.25) / 0.25;
    return `rgb(${Math.round(20 + t * 20)}, ${Math.round(76 + t * 140)}, ${Math.round(98 + t * 65)})`;
  }
  if (x < 0.75) {
    const t = (x - 0.5) / 0.25;
    return `rgb(${Math.round(40 + t * 190)}, ${Math.round(216 + t * 20)}, ${Math.round(163 - t * 100)})`;
  }
  const t = (x - 0.75) / 0.25;
  return `rgb(${Math.round(230 + t * 25)}, ${Math.round(236 + t * 19)}, ${Math.round(63 + t * 170)})`;
}

function drawWaterfall(payload) {
  const ctx = waterfallCanvas.getContext("2d");
  const rect = waterfallCanvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  waterfallCanvas.width = Math.max(1, Math.floor(rect.width * dpr));
  waterfallCanvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#08121f";
  ctx.fillRect(0, 0, width, height);

  if (!payload?.available || !Array.isArray(payload.matrix) || payload.matrix.length === 0) {
    waterfallStatus.textContent = payload?.message || "等待音频分片";
    ctx.fillStyle = "#cbd5e1";
    ctx.font = "14px sans-serif";
    ctx.fillText(waterfallStatus.textContent, 20, 34);
    return;
  }

  waterfallStatus.textContent = `${payload.minHz}-${payload.maxHz} Hz · ${payload.sampleRate} Hz`;
  const matrix = payload.matrix;
  const timeBins = matrix.length;
  const freqBins = matrix[0]?.length || 0;
  const padLeft = 50;
  const padRight = 12;
  const padTop = 12;
  const padBottom = 28;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const cellW = plotW / Math.max(1, timeBins);
  const cellH = plotH / Math.max(1, freqBins);

  for (let t = 0; t < timeBins; t += 1) {
    for (let f = 0; f < freqBins; f += 1) {
      ctx.fillStyle = colorForWaterfall(matrix[t][f]);
      const x = padLeft + t * cellW;
      const y = padTop + (freqBins - 1 - f) * cellH;
      ctx.fillRect(x, y, Math.ceil(cellW) + 0.5, Math.ceil(cellH) + 0.5);
    }
  }

  ctx.strokeStyle = "#d1d5db";
  ctx.lineWidth = 1;
  ctx.strokeRect(padLeft, padTop, plotW, plotH);
  ctx.fillStyle = "#334155";
  ctx.font = "12px sans-serif";
  ctx.fillText(`${payload.maxHz} Hz`, 6, padTop + 12);
  ctx.fillText(`${payload.minHz} Hz`, 6, padTop + plotH);
  ctx.fillText("time", padLeft + plotW - 28, height - 8);
}

function renderJudgments(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) {
    judgmentBody.innerHTML = '<tr><td colspan="7">暂无判断结果</td></tr>';
    return;
  }
  judgmentBody.innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${item.time ?? "-"}</td>
          <td>${item.decisionAction ?? "-"}</td>
          <td>${ratioText(item.fishRatio)}</td>
          <td>${ratioText(item.windowFishRatio)}</td>
          <td>${ratioText(item.baselineFishRatio)}</td>
          <td>${signedRatioText(item.relativeFishDelta)}</td>
          <td>${item.strategyReason ?? "-"}</td>
        </tr>
      `
    )
    .join("");
}

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

async function loadData() {
  try {
    const [data, agent, judgments, waterfall] = await Promise.all([
      getJSON("/realtime/data"),
      getJSON("/agent/state"),
      getJSON("/realtime/judgments"),
      getJSON("/realtime/waterfall"),
    ]);
    applyData(data);
    applyAgent(agent);
    renderJudgments(judgments);
    drawWaterfall(waterfall);
  } catch (err) {
    console.error(err);
  }
}

async function callAction(path) {
  try {
    const res = await getJSON(path);
    if (res.data) applyData(res.data);
  } catch (err) {
    alert(`请求失败: ${err.message}`);
  }
}

async function startCollect() {
  try {
    const monitor = await getJSON("/realtime/start");
    if (monitor.data) applyData(monitor.data);
    const control = await getJSON("/agent/collect/start");
    if (control.data) applyAgent(control.data);
    await loadData();
  } catch (err) {
    alert(`开始采集失败: ${err.message}`);
  }
}

async function stopCollect() {
  try {
    const control = await getJSON("/agent/collect/stop");
    if (control.data) applyAgent(control.data);
    const monitor = await getJSON("/realtime/stop");
    if (monitor.data) applyData(monitor.data);
    await loadData();
  } catch (err) {
    alert(`停止采集失败: ${err.message}`);
  }
}

document.getElementById("btnStart").addEventListener("click", startCollect);
document.getElementById("btnStop").addEventListener("click", stopCollect);
document.getElementById("btnReset").addEventListener("click", () => callAction("/realtime/reset"));
document.getElementById("btnRefresh").addEventListener("click", () => loadData());

document.getElementById("uploadForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fileInput = document.getElementById("audioFile");
  const deviceIdInput = document.getElementById("deviceId");
  const resultEl = document.getElementById("uploadResult");
  if (!fileInput.files || !fileInput.files[0]) return;

  const form = new FormData();
  form.append("file", fileInput.files[0]);
  form.append("deviceId", deviceIdInput.value || "web-debug-device");
  form.append("collectedAt", new Date().toISOString().slice(0, 19).replace("T", " "));

  try {
    const res = await fetch(`${API_BASE}/realtime/chunk/upload`, {
      method: "POST",
      body: form,
    });
    const data = await res.json();
    resultEl.textContent = JSON.stringify(data, null, 2);
    if (data.data) applyData(data.data);
    await loadData();
  } catch (err) {
    resultEl.textContent = `upload error: ${err.message}`;
  }
});

loadData();
setInterval(loadData, REFRESH_MS);
